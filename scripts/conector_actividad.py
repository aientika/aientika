"""Informe de uso de Aiéntika (lo corre el administrador): quién se conectó, cuándo, con qué herramientas y qué buscó.

    python scripts/conector_actividad.py                                   # resumen por invitado
    python scripts/conector_actividad.py --consultas [--invitado ID] [--dias N]   # el texto de las consultas (aviso v2)
    python scripts/conector_actividad.py --visitas [--invitado ID] [--dias N]     # visitas al sitio unidas a su búsqueda (aviso v3)

Conexión por las mismas variables de entorno que
`scripts/conector_invitados.py` (`REPLICA_DB_HOST` o `REPLICA_DB_INSTANCIA`, `REPLICA_DB_USER`, `REPLICA_DB_PASSWORD`), con el rol
dueño o con `conector`. Solo lee: no escribe a disco ni a la base, y no imprime correos, hashes, `jti` ni tokens. Las horas van en
hora de Costa Rica (UTC-6, sin horario de verano). El texto de las consultas existe solo para credenciales que aceptaron el aviso v2
y solo por 90 días (registro.py); una consulta sin fila acá no prueba que no se hizo: puede ser de una credencial con el aviso v1.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src.conector import bd  # noqa: E402
from src.conector.registro import DIAS_RETENCION_CONSULTAS  # noqa: E402
from src.conector.visitas import MARCA as VISITA, PREFIJO_BUSQUEDA  # noqa: E402

CR = timezone(timedelta(hours=-6))


def hora_cr(ts: int | None) -> str:
    """Epoch en segundos -> 'AAAA-MM-DD HH:MM' en hora de Costa Rica ('-' si no hay)."""
    return datetime.fromtimestamp(int(ts), CR).strftime("%Y-%m-%d %H:%M") if ts is not None else "-"


def _etiquetas(cur) -> dict[str, tuple[str, bool]]:
    cur.execute("SELECT id, etiqueta, activo FROM invitado ORDER BY creado_ts")
    return {f[0]: (f[1] or "(sin etiqueta)", bool(f[2])) for f in cur.fetchall()}


def informe(cur) -> list[str]:
    """Líneas del resumen por invitado: etiqueta, primera y última llamada, sesiones, llamadas por herramienta, búsquedas por día,
    duración media y máxima, y errores. Incluye a los invitados que nunca llamaron (con sus sesiones) y a ids sin invitado."""
    etiquetas = _etiquetas(cur)
    cur.execute("SELECT invitado_id, count(*) FROM credencial GROUP BY invitado_id")
    sesiones = {f[0]: int(f[1]) for f in cur.fetchall()}
    cur.execute("SELECT invitado_id, ts, herramienta, resultado, duracion_ms FROM conector_llamada ORDER BY ts")
    llamadas: dict[str, list] = defaultdict(list)
    for inv, ts, herramienta, resultado, duracion in cur.fetchall():
        llamadas[inv or "(sin invitado)"].append((int(ts), herramienta, resultado, duracion))

    ids = list(etiquetas) + sorted(set(llamadas) - set(etiquetas))
    salida = [f"Aiéntika: actividad por invitado ({len(ids)} invitado(s)); horas en hora de Costa Rica", ""]
    for id_ in ids:
        etiqueta, activo = etiquetas.get(id_, ("(no está en la tabla de invitados)", False))
        filas = llamadas.get(id_, [])
        salida.append(f"{id_}  {etiqueta}  [{'activo' if activo else 'de baja'}]")
        salida.append(f"  sesiones (credenciales emitidas): {sesiones.get(id_, 0)}")
        if not filas:
            salida += ["  llamadas: 0", ""]
            continue
        salida.append(f"  primera llamada: {hora_cr(filas[0][0])}   última: {hora_cr(filas[-1][0])}   total: {len(filas)}")
        por_herramienta = Counter(f[1] for f in filas)
        salida.append("  por herramienta: " + ", ".join(f"{h} {n}" for h, n in sorted(por_herramienta.items())))
        por_dia = Counter(hora_cr(f[0])[:10] for f in filas if f[1] == "buscar")
        salida.append("  búsquedas por día: " + (", ".join(f"{d} {n}" for d, n in sorted(por_dia.items())) or "ninguna"))
        duraciones = [f[3] for f in filas if f[3] is not None]
        if duraciones:
            salida.append(f"  duración: media {sum(duraciones) / len(duraciones) / 1000:.1f} s, máxima {max(duraciones) / 1000:.1f} s")
        errores = Counter(f[2] for f in filas if f[2] != "ok")
        salida.append("  errores y límites: " + (", ".join(f"{r} {n}" for r, n in sorted(errores.items())) or "ninguno"))
        salida.append("")
    return salida


def consultas(cur, ahora_ts: int, dias: int = DIAS_RETENCION_CONSULTAS, invitado: str | None = None) -> list[str]:
    """Líneas con cada consulta guardada (hora de Costa Rica, invitado, herramienta, texto y filtros), de la más vieja a la más nueva."""
    etiquetas = _etiquetas(cur)
    sql = "SELECT ts, invitado_id, herramienta, texto, filtros FROM conector_consulta WHERE ts >= %s"
    params: list = [ahora_ts - dias * 86400]
    if invitado:
        sql += " AND invitado_id = %s"
        params.append(invitado)
    cur.execute(sql + " ORDER BY ts", tuple(params))
    filas = cur.fetchall()
    salida = [f"Consultas guardadas de los últimos {dias} día(s){' de ' + invitado if invitado else ''}: {len(filas)} "
              "(solo credenciales con el aviso v2; horas de Costa Rica)", ""]
    for ts, inv, herramienta, texto, filtros in filas:
        etiqueta = etiquetas.get(inv, ("?", False))[0]
        extra = ""
        if filtros:
            try:
                extra = "  [" + ", ".join(f"{k}={v}" for k, v in json.loads(filtros).items()) + "]"
            except ValueError:
                extra = "  [filtros ilegibles]"
        salida.append(f"{hora_cr(ts)}  {inv} ({etiqueta})  {herramienta}: «{texto}»{extra}")
    return salida


def visitas(cur, ahora_ts: int, dias: int = DIAS_RETENCION_CONSULTAS, invitado: str | None = None) -> list[str]:
    """Cada visita al sitio unida (referencia_visita): quién, desde qué asistente, a qué página y qué búsqueda la originó. La
    búsqueda es la última `buscar` guardada del invitado hasta la hora que trae la referencia; si no hay texto guardado, se dice."""
    etiquetas = _etiquetas(cur)
    sql = "SELECT ts, invitado_id, resultado, via, cliente FROM conector_llamada WHERE herramienta = %s AND ts >= %s"
    params: list = [VISITA, ahora_ts - dias * 86400]
    if invitado:
        sql += " AND invitado_id = %s"
        params.append(invitado)
    cur.execute(sql + " ORDER BY ts", tuple(params))
    filas = cur.fetchall()
    salida = [f"Visitas al sitio unidas a su búsqueda, últimos {dias} día(s): {len(filas)} (credenciales con el aviso v3; horas de Costa Rica)", ""]
    for ts, inv, resultado, via, pagina in filas:
        busqueda = "(búsqueda sin texto guardado)"
        if resultado and resultado.startswith(PREFIJO_BUSQUEDA) and resultado[len(PREFIJO_BUSQUEDA):].isdigit():
            ts_b = int(resultado[len(PREFIJO_BUSQUEDA):])
            cur.execute("SELECT texto FROM conector_consulta WHERE invitado_id = %s AND herramienta = %s AND ts <= %s AND ts >= %s "
                        "ORDER BY ts DESC LIMIT 1", (inv, "buscar", ts_b, ts_b - 600))
            f = cur.fetchone()
            if f:
                busqueda = f"«{f[0]}» ({hora_cr(ts_b)})"
        salida.append(f"{hora_cr(ts)}  {inv} ({etiquetas.get(inv, ('?', False))[0]})  desde {via} a {pagina}  <- {busqueda}")
    return salida


def main(argv: list[str] | None = None) -> int:
    """Imprime el resumen por invitado o, con `--consultas`, el texto de las consultas. Devuelve 0."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--consultas", action="store_true", help="lista el texto de las consultas guardadas (aviso v2)")
    p.add_argument("--visitas", action="store_true", help="lista las visitas al sitio unidas a su búsqueda (aviso v3)")
    p.add_argument("--invitado", help="con --consultas o --visitas: solo las de este id de invitado")
    p.add_argument("--dias", type=int, default=DIAS_RETENCION_CONSULTAS, help="con --consultas: cuántos días hacia atrás")
    args = p.parse_args(argv)
    with bd.estado() as conn:
        cur = conn.cursor()
        if args.visitas:
            lineas = visitas(cur, int(time.time()), args.dias, args.invitado)
        elif args.consultas:
            lineas = consultas(cur, int(time.time()), args.dias, args.invitado)
        else:
            lineas = informe(cur)
    print("\n".join(lineas))
    return 0


if __name__ == "__main__":
    sys.exit(main())
