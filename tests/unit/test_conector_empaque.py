"""Empaque del conector: el Dockerfile copia exactamente lo que se importa, no define el modo sin auth, y el deploy declara el ref y no ejecuta nada.

El cierre de imports se recalcula por AST (incluye los imports dentro de funciones); la imagen se prueba COPIANDO solo esos archivos a un
directorio vacío e importando el servidor ahí, sin el resto del repo (lo que se verifica es que el empaque arranca, no que la lista parezca bien).
"""

import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DOCKERFILE = (RAIZ / "Dockerfile.conector").read_text(encoding="utf-8")
DEPLOY = (RAIZ / "scripts" / "deploy_conector.sh").read_text(encoding="utf-8")


def cierre(*raices: str) -> set[str]:
    """Rutas (relativas) de los módulos `src.*` que importa, directa o transitivamente, alguno de `raices`."""
    vistos, pendientes = set(), list(raices)
    while pendientes:
        m = pendientes.pop()
        ruta = RAIZ / (m.replace(".", "/") + ".py")
        if m in vistos or not ruta.exists():
            continue
        vistos.add(m)
        for n in ast.walk(ast.parse(ruta.read_text(encoding="utf-8"))):
            if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("src."):
                pendientes += [n.module] + [f"{n.module}.{a.name}" for a in n.names]
            elif isinstance(n, ast.Import):
                pendientes += [a.name for a in n.names if a.name.startswith("src.")]
    return {m.replace(".", "/") + ".py" for m in vistos}


def copiados_por_el_dockerfile() -> set[str]:
    """Archivos que nombran las líneas COPY; un directorio se expande a sus .py."""
    salida = set()
    for linea in DOCKERFILE.splitlines():
        if not linea.startswith("COPY "):
            continue
        *origenes, _destino = linea.split()[1:]
        for o in origenes:
            if not o.endswith(".py") and not (RAIZ / o).is_dir():  # el lockfile de dependencias no es código del conector
                continue
            p = RAIZ / o
            salida |= {str(x.relative_to(RAIZ)).replace("\\", "/") for x in p.rglob("*.py")} if p.is_dir() else {o}
    return salida


# Módulos construidos pero TODAVÍA no conectados a la pantalla, declarados a propósito (no hay código muerto: esto es una etapa, no un resto).
# `codigo_correo.py` lo conectará la pantalla de dos pasos y ENTONCES sale de esta lista.
EN_CONSTRUCCION = {"src/conector/codigo_correo.py"}


def test_lo_declarado_en_construccion_sigue_sin_conectar_y_en_cuanto_se_conecta_sale_de_la_lista():
    """Si la lista pudiera quedarse, escondería código muerto para siempre: un módulo ya importado por el servidor no puede figurar aquí."""
    necesario = cierre("src.conector.servidor", "src.conector.esquema_conector", "src.indice.postgres")
    for modulo in EN_CONSTRUCCION:
        assert (RAIZ / modulo).exists(), f"{modulo} figura en construcción pero no existe: sacarlo de la lista"
        assert modulo not in necesario, f"{modulo} ya lo importa el servidor: sacarlo de EN_CONSTRUCCION (ya no está en construcción)"


def test_el_dockerfile_copia_todo_lo_que_se_importa_y_nada_de_mas():
    necesario = cierre("src.conector.servidor", "src.conector.esquema_conector", "src.indice.postgres")
    copiado = copiados_por_el_dockerfile()
    assert necesario - copiado == set(), f"faltan en la imagen: {sorted(necesario - copiado)}"
    sobran = {c for c in copiado - necesario if "__pycache__" not in c and not c.endswith("__init__.py") and c not in EN_CONSTRUCCION}
    assert sobran == set(), f"la imagen copia de más: {sorted(sobran)}"


def datos_copiados_por_el_dockerfile() -> set[str]:
    """Los archivos que NO son .py dentro de los directorios que copia el Dockerfile (Docker los copia enteros): la página del sitio
    (`src/conector/sitio/`) y los datos que el conector lee al importar."""
    salida = set()
    for linea in DOCKERFILE.splitlines():
        if linea.startswith("COPY "):
            for o in linea.split()[1:-1]:
                if (RAIZ / o).is_dir():
                    salida |= {str(x.relative_to(RAIZ)).replace("\\", "/") for x in (RAIZ / o).rglob("*")
                               if x.is_file() and x.suffix not in (".py", ".pyc") and "__pycache__" not in x.parts}
    return salida


def importar_en_aislado(tmp_path, excluir=frozenset()):
    """Copia a `tmp_path` los archivos de la imagen (menos `excluir`) e importa el servidor ahí, sin el resto del repo."""
    for rel in (copiados_por_el_dockerfile() | datos_copiados_por_el_dockerfile()) - excluir:
        destino = tmp_path / rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(RAIZ / rel, destino)
    return subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, '.'); import src.conector.servidor as s; print(s.CONECTOR_VERSION)"],
                          cwd=tmp_path, capture_output=True, text=True, stdin=subprocess.DEVNULL)


def test_el_servidor_importa_en_un_directorio_con_solo_lo_que_copia_la_imagen(tmp_path):
    from src.conector.version import CONECTOR_VERSION
    r = importar_en_aislado(tmp_path)
    assert r.returncode == 0 and r.stdout.strip() == CONECTOR_VERSION, r.stderr[-800:]


def test_control_negativo_sin_un_modulo_el_import_falla(tmp_path):
    r = importar_en_aislado(tmp_path, excluir={"src/indice/extracto.py"})
    assert r.returncode != 0 and "extracto" in r.stderr


def test_el_init_de_apoyo_no_viaja():
    # El paquete de apoyo se copia sin `__init__.py` para no arrastrar dependencias de más.
    assert "src/apoyo/__init__.py" not in copiados_por_el_dockerfile()


def test_cmd_directo_sin_entrypoint_y_sin_root_ni_credenciales():
    assert re.search(r'^CMD \["python", "-m", "src\.conector\.servidor"\]$', DOCKERFILE, re.M)
    assert "ENTRYPOINT" not in DOCKERFILE and "entrypoint.sh" not in DOCKERFILE.replace("sin entrypoint.sh", "")
    assert "USER conector" in DOCKERFILE
    assert not re.search(r"(PASSWORD|API_KEY|SECRET)\s*=\s*\S", DOCKERFILE)


def test_ni_el_dockerfile_ni_el_deploy_definen_el_modo_sin_autenticacion():
    for texto in (DOCKERFILE, DEPLOY):
        assert not re.search(r"CONECTOR_SIN_AUTH\s*=", texto) and not re.search(r"ENV\s+CONECTOR_SIN_AUTH", texto)


def test_el_deploy_no_ejecuta_nada_declara_el_ref_y_usa_secretos_y_vpc():
    assert "set -euo pipefail" in DEPLOY and "git status --short" in DEPLOY and "git rev-parse HEAD" in DEPLOY
    assert "origin/main..HEAD" in DEPLOY and "HEAD..origin/main" in DEPLOY  # diferencias en ambos sentidos
    ejecutables = [x for x in DEPLOY.splitlines() if re.match(r"^\s*gcloud ", x)]
    assert ejecutables == [], "el script solo debe IMPRIMIR gcloud (dentro de echo)"
    for requerido in ("--min-instances=0", "--network=", "--subnet=", "--vpc-egress=", "--set-secrets=", "REPLICA_DB_PASSWORD=${SECRETO_BD}", 'SECRETO_BD="db-password-conector"',
                      "VOYAGE_API_KEY=", "CONECTOR_FIRMA_SECRET=", "REPLICA_DB_HOST=", "CONECTOR_URL_PUBLICA=", "--region=${REGION}", "us-east1"):
        assert requerido in DEPLOY, requerido
    assert "--allow-unauthenticated" in DEPLOY and "password=" not in DEPLOY.lower().replace("replica_db_password=", "")


# --- imagen reproducible----------------------------------------------------------------------

LOCK = RAIZ / "requirements-conector.txt"


def fijadas_en_el_lock() -> dict[str, str]:
    """`nombre canónico -> versión` de cada línea `nombre==versión` del lockfile."""
    from packaging.utils import canonicalize_name
    salida = {}
    for linea in LOCK.read_text(encoding="utf-8").splitlines():
        linea = linea.split("#", 1)[0].strip().rstrip("\\").strip()
        if linea and not linea.startswith("--"):
            nombre, version = linea.split("==")
            salida[canonicalize_name(nombre)] = version.strip()
    return salida


def cierre_instalado(raices=("mcp", "pg8000")) -> dict[str, str]:
    """Versiones INSTALADAS del cierre de dependencias de `raices`, con los marcadores evaluados para Linux (la imagen)."""
    from importlib import metadata

    from packaging.markers import default_environment
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    entorno = {**default_environment(), "sys_platform": "linux", "platform_system": "Linux", "os_name": "posix"}
    vistos: dict[str, set] = {}
    pendientes = [(r, frozenset()) for r in raices]
    while pendientes:
        nombre, extras = pendientes.pop()
        n = canonicalize_name(nombre)
        if n in vistos and extras <= vistos[n]:
            continue
        vistos[n] = vistos.get(n, set()) | extras
        for texto in metadata.requires(n) or []:
            req = Requirement(texto)
            if req.marker is None or any(req.marker.evaluate({**entorno, "extra": e}) for e in ("", *vistos[n])):
                pendientes.append((req.name, frozenset(req.extras)))
    return {n: metadata.version(n) for n in vistos}


def diferencias_con_el_lock(fijadas: dict[str, str], instaladas: dict[str, str]) -> list[str]:
    """Lo que falta, sobra o difiere entre el lock y lo instalado; vacío si coinciden."""
    salida = [f"falta {n}" for n in sorted(set(instaladas) - set(fijadas))]
    salida += [f"sobra {n}" for n in sorted(set(fijadas) - set(instaladas))]
    return salida + [f"{n}: lock {fijadas[n]} / instalado {instaladas[n]}" for n in sorted(fijadas)
                     if n in instaladas and fijadas[n] != instaladas[n]]


def test_el_lockfile_fija_todo_el_cierre_con_las_versiones_que_corre_la_suite():
    fijadas = fijadas_en_el_lock()
    assert diferencias_con_el_lock(fijadas, cierre_instalado()) == []
    assert {"starlette", "uvicorn", "pydantic", "pyjwt", "httpx"} <= set(fijadas)  # las transitivas que antes se resolvían el día del build


def test_control_negativo_una_version_distinta_o_una_transitiva_de_menos_se_detecta():
    fijadas, instaladas = fijadas_en_el_lock(), cierre_instalado()
    assert diferencias_con_el_lock({**fijadas, "starlette": "0.0.1"}, instaladas) == ["starlette: lock 0.0.1 / instalado " + instaladas["starlette"]]
    assert diferencias_con_el_lock({n: v for n, v in fijadas.items() if n != "uvicorn"}, instaladas) == ["falta uvicorn"]


def sin_hash(texto: str) -> list[str]:
    """Paquetes del lock (`nombre==versión`) que no traen ninguna línea `--hash=sha256:` debajo."""
    salida, actual, con_hash = [], None, False
    for linea in texto.splitlines():
        limpia = linea.split("#", 1)[0].strip()
        if not limpia:
            continue
        if limpia.startswith("--hash=sha256:"):
            con_hash = True
            continue
        if "==" in limpia:
            if actual and not con_hash:
                salida.append(actual)
            actual, con_hash = limpia.split("==")[0].strip(), "--hash=sha256:" in limpia
    if actual and not con_hash:
        salida.append(actual)
    return salida


def test_cada_paquete_del_lock_trae_hash():
    texto = LOCK.read_text(encoding="utf-8")
    assert sin_hash(texto) == []
    assert len(re.findall(r"--hash=sha256:[0-9a-f]{64}", texto)) >= len(fijadas_en_el_lock())


def test_control_negativo_un_paquete_sin_hash_se_detecta():
    texto = LOCK.read_text(encoding="utf-8")
    assert sin_hash(texto + "\nfalso-paquete==1.0\n") == ["falso-paquete"]
    sin_el_primero = re.sub(r"(?m)^(anyio==\S+) \\\n(    --hash=\S+(?: \\)?\n)+", r"\1\n", texto)
    assert "anyio" in sin_hash(sin_el_primero)


def test_la_imagen_instala_solo_el_lock_sin_resolver_y_con_la_misma_version_menor_de_python():
    assert re.search(r"^RUN pip install --no-cache-dir --no-deps --require-hashes --only-binary :all: "
                     r"-r /tmp/requirements-conector\.txt && pip check$", DOCKERFILE, re.M)
    assert "COPY requirements-conector.txt /tmp/requirements-conector.txt" in DOCKERFILE
    assert not re.search(r"pip install[^\n]*\b(mcp|pg8000)==", DOCKERFILE)  # nada fijado a mano fuera del lock
    menor = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert re.search(rf"^FROM python:{re.escape(menor)}-slim$", DOCKERFILE, re.M), f"la suite corre en {menor}"


def clon_seguro(script: str) -> bool:
    """El clon del deploy admite rutas largas, conserva los finales de línea y aborta si el árbol no quedó entero."""
    clon = next((l for l in script.splitlines() if "git clone" in l), "")
    return ("-c core.longpaths=true" in clon and "-c core.autocrlf=false" in clon
            and bool(re.search(r"test -z .*git -C .*status --short.*ABORTADO", script)))


def test_el_clon_del_deploy_admite_rutas_largas_y_aborta_si_queda_a_medias():
    # Sin core.longpaths el checkout falló en Windows y Cloud Build empaquetó un clon a medias.
    assert clon_seguro(DEPLOY)
    assert not clon_seguro(DEPLOY.replace(" -c core.longpaths=true", ""))  # control negativo
    assert not clon_seguro(re.sub(r"(?m)^.*status --short.*ABORTADO.*$", "", DEPLOY))


def test_el_deploy_separa_las_variables_con_un_delimitador_que_no_es_la_coma():
    linea = next(x for x in DEPLOY.splitlines() if "--set-env-vars=" in x)
    valores = linea.split("--set-env-vars=", 1)[1]
    assert valores.startswith("^@^") and "," not in valores.split(" ")[0], linea  # una lista con comas se partiría
    assert "421" in DEPLOY and "${URL}/mcp" in DEPLOY  # la invitación lleva la URL exacta


def test_el_deploy_no_contiene_ningun_secreto():
    assert not re.search(r"(?i)(api[_-]?key|secret|password)\s*=\s*['\"]?[A-Za-z0-9+/_\-]{20,}", DEPLOY)
