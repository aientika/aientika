"""Límites del conector, contados ANTES de ejecutar y de forma atómica en Postgres.

Los modelos lanzan herramientas en paralelo y no obedecen instrucciones: el tope vive en la base. Un
solo UPSERT condicional por contador (`INSERT … ON CONFLICT DO UPDATE … WHERE unidades + n <= tope RETURNING`) decide quién pasa;
los contadores de una llamada (ventana de 4 h, semana, tope global del día) se toman en UNA transacción y en orden fijo, así que
ninguna llamada consume parte de su cupo y falla en el resto, y dos transacciones no se bloquean entre sí. Ventanas fijas en hora de
Costa Rica (UTC-6, sin horario de verano): 0, 4, 8, 12, 16 y 20 h; semana de lunes 00:00 a domingo 23:59. El reloj se inyecta.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from src.conector import bd, presupuesto

CR = timezone(timedelta(hours=-6))
HORAS_VENTANA = 4
BUSCAR_POR_VENTANA = 15  # unidades de `buscar` por ventana de 4 h (≈ 5 preguntas)
BUSCAR_POR_SEMANA = 60  # ≈ 20 preguntas
FICHA_POR_DIA = 60
VERIFICAR_POR_DIA = 100
REPORTAR_POR_DIA = 20
AYUDA_POR_DIA = 200  # no gasta cupo de búsqueda, pero abre conexiones: sin tope, un bucle saturaría el servicio
TOPE_GLOBAL_DIA = 1000  # unidades de `buscar`, `ficha` y `verificar_cita` entre todos los invitados
# Cupo de administrador: los topes POR INVITADO se multiplican; el global no, porque protege al servicio. Los
# administradores son ids de invitado en `CONECTOR_ADMINISTRADORES` (separados por coma), leída en cada llamada:
# cambiarla no exige migrar la base.
FACTOR_ADMINISTRADOR = 10
VARIABLE_ADMINISTRADORES = "CONECTOR_ADMINISTRADORES"
HORA_APERTURA = 7
HORA_CIERRE = 23
# El conector atiende las 24 horas. El horario restringido (7:00 a 23:00) se conserva solo para poder volver atrás:
# con False, todo lo de abajo vuelve a regir sin tocar nada más.
SERVICIO_24_HORAS = True
HORARIO_LEGIBLE = "las 24 horas" if SERVICIO_24_HORAS else "de 7:00 a 23:00, hora de Costa Rica"
MENSAJE_FUERA_DE_HORARIO = "El servicio está disponible de 7:00 a 23:00 (hora de Costa Rica). Probá de nuevo en ese horario."
_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

_UPSERT = (
    "INSERT INTO uso (clave, ventana, unidades) SELECT CAST(%s AS TEXT), CAST(%s AS TEXT), CAST(%s AS BIGINT) "
    "WHERE CAST(%s AS BIGINT) <= CAST(%s AS BIGINT) "
    "ON CONFLICT (clave, ventana) DO UPDATE SET unidades = uso.unidades + CAST(%s AS BIGINT) "
    "WHERE uso.unidades + CAST(%s AS BIGINT) <= CAST(%s AS BIGINT) RETURNING unidades"
)


@dataclass(frozen=True)
class Regla:
    """Un contador: `clave` (quién y qué), `ventana` (cuándo), su `tope`, cuándo se `renueva` y cómo se nombra al explicar."""

    clave: str
    ventana: str
    tope: int
    renueva: datetime
    nombre: str
    global_: bool = False


@dataclass(frozen=True)
class Veredicto:
    """Resultado de contar una llamada: `permitido`, o el `mensaje` en palabras de por qué no."""

    permitido: bool
    mensaje: str | None = None
    cupo: str | None = None  # en `buscar`: lo que queda, en palabras, para que Claude se lo diga al usuario


def en_cr(ahora: datetime) -> datetime:
    """El instante en hora de Costa Rica."""
    return ahora.astimezone(CR)


def fuera_de_horario(ahora: datetime) -> bool:
    """True fuera de 7:00-23:00 hora de Costa Rica; siempre False con `SERVICIO_24_HORAS`."""
    if SERVICIO_24_HORAS:
        return False
    return not time(HORA_APERTURA) <= en_cr(ahora).time() < time(HORA_CIERRE)


def inicio_ventana(ahora: datetime) -> datetime:
    """Inicio de la ventana fija de 4 h que contiene `ahora`."""
    t = en_cr(ahora)
    return t.replace(hour=t.hour - t.hour % HORAS_VENTANA, minute=0, second=0, microsecond=0)


def inicio_semana(ahora: datetime) -> datetime:
    """Lunes 00:00 (hora de Costa Rica) de la semana de `ahora`."""
    t = en_cr(ahora).replace(hour=0, minute=0, second=0, microsecond=0)
    return t - timedelta(days=t.weekday())


def inicio_dia(ahora: datetime) -> datetime:
    """Las 00:00 (hora de Costa Rica) del día de `ahora`."""
    return en_cr(ahora).replace(hour=0, minute=0, second=0, microsecond=0)


def hora_legible(t: datetime, ahora: datetime) -> str:
    """«a las 12:00» si es hoy, «mañana a las 7:00», o «el lunes 16 a las 7:00»; siempre hora de Costa Rica.

    Si el instante cae con el servicio cerrado (por ejemplo la medianoche), se dice desde cuándo atiende de nuevo.
    """
    t = en_cr(t)
    if not SERVICIO_24_HORAS and t.hour < HORA_APERTURA:
        t = t.replace(hour=HORA_APERTURA, minute=0)
    dias = (t.date() - en_cr(ahora).date()).days
    hhmm = f"{t.hour}:{t.minute:02d}"
    if dias <= 0:
        return f"hoy a las {hhmm}"
    if dias == 1:
        return f"mañana a las {hhmm}"
    return f"el {_DIAS[t.weekday()]} {t.day} a las {hhmm}"


def es_administrador(invitado: str | None) -> bool:
    """¿El invitado está en `CONECTOR_ADMINISTRADORES`? Se lee en cada llamada (sin caché: el cambio rige en la siguiente)."""
    ids = {x.strip() for x in os.environ.get(VARIABLE_ADMINISTRADORES, "").split(",") if x.strip()}
    return bool(invitado) and invitado in ids


FIJOS = presupuesto.Topes(TOPE_GLOBAL_DIA, BUSCAR_POR_SEMANA, False)


def topes_de_hoy(cur, ahora: datetime) -> presupuesto.Topes:
    """Los topes que rigen hoy: los de la capa dinámica si hay presupuesto (`presupuesto.py`), si no los fijos."""
    return presupuesto.topes(cur, en_cr(ahora), FIJOS)


def reglas(herramienta: str, invitado: str, ahora: datetime, topes: presupuesto.Topes = FIJOS) -> list[Regla]:
    """Los contadores que gasta una llamada de `herramienta` (en orden fijo: evita bloqueos entre transacciones).

    `topes` trae el global del día y el semanal de `buscar` (fijos, o los de la capa dinámica); la clave y la ventana de cada
    contador no dependen de ellos, así que `devolver` puede usar los fijos sin tocar otro contador.
    """
    dia = inicio_dia(ahora)
    manana = dia + timedelta(days=1)
    f = FACTOR_ADMINISTRADOR if es_administrador(invitado) else 1
    glob = Regla("global", f"dia:{dia:%Y-%m-%d}", topes.global_dia, manana, "el tope diario del servicio", True)
    if herramienta in ("buscar", "tramites_buscar"):  # mismo cupo: las mismas claves
        v, s = inicio_ventana(ahora), inicio_semana(ahora)
        tv, ts = BUSCAR_POR_VENTANA * f, topes.buscar_semana * f
        return [Regla(f"{invitado}:buscar", f"v{HORAS_VENTANA}h:{v:%Y-%m-%dT%H}", tv,
                      v + timedelta(hours=HORAS_VENTANA), f"tus {tv} búsquedas de cada {HORAS_VENTANA} horas"),
                Regla(f"{invitado}:buscar", f"sem:{s:%Y-%m-%d}", ts, s + timedelta(days=7),
                      f"tus {ts} búsquedas de la semana"), glob]
    if herramienta == "ficha":
        return [Regla(f"{invitado}:ficha", f"dia:{dia:%Y-%m-%d}", FICHA_POR_DIA * f, manana, f"tus {FICHA_POR_DIA * f} fichas del día"),
                glob]
    if herramienta == "verificar_cita":
        return [Regla(f"{invitado}:verificar_cita", f"dia:{dia:%Y-%m-%d}", VERIFICAR_POR_DIA * f, manana,
                      f"tus {VERIFICAR_POR_DIA * f} verificaciones del día"), glob]
    if herramienta == "reportar":
        return [Regla(f"{invitado}:reportar", f"dia:{dia:%Y-%m-%d}", REPORTAR_POR_DIA, manana,
                      f"tus {REPORTAR_POR_DIA} reportes del día")]
    if herramienta == "ayuda":
        return [Regla(f"{invitado}:ayuda", f"dia:{dia:%Y-%m-%d}", AYUDA_POR_DIA, manana, f"tus {AYUDA_POR_DIA} consultas de ayuda del día")]
    return []


def tomar(cur, clave: str, ventana: str, tope: int, cantidad: int = 1) -> int | None:
    """Toma `cantidad` unidades del contador (clave, ventana) si no pasa de `tope`. El UPSERT condicional decide, atómico.

    Devuelve las unidades usadas tras tomarlas (siempre >= `cantidad`), o None si no alcanzaban.
    """
    cur.execute(_UPSERT, (clave, ventana, cantidad, cantidad, tope, cantidad, cantidad, tope))
    fila = cur.fetchone()
    return int(fila[0]) if fila else None


def _usadas(cur, regla: Regla) -> int:
    cur.execute("SELECT unidades FROM uso WHERE clave = %s AND ventana = %s", (regla.clave, regla.ventana))
    fila = cur.fetchone()
    return int(fila[0]) if fila else 0


def _mensaje_agotado(regla: Regla, ahora: datetime) -> str:
    cuando = hora_legible(regla.renueva, ahora)
    if regla.global_:
        return f"El servicio alcanzó {regla.nombre} y no atiende más consultas por hoy. Se renueva {cuando} (hora de Costa Rica)."
    return (f"Se agotaron {regla.nombre}. Se renuevan {cuando} (hora de Costa Rica). Mientras tanto podés seguir "
            "usando `ficha` y `verificar_cita` sobre los fallos que ya tenés.")


def _cupo_buscar(usadas: list[int], lista: list[Regla], ahora: datetime) -> str:
    v, sem = lista[0], lista[1]
    return (f"Te quedan {v.tope - usadas[0]} de {v.tope} búsquedas en esta ventana (se renueva {hora_legible(v.renueva, ahora)}) "
            f"y {sem.tope - usadas[1]} de {sem.tope} esta semana (hora de Costa Rica).")


def consumir(herramienta: str, invitado: str, ahora: datetime, cantidad: int = 1) -> Veredicto:
    """Cuenta `cantidad` unidades ANTES de ejecutar. Todo o nada: si un contador no alcanza, ninguno se descuenta."""
    if not reglas(herramienta, invitado, ahora):
        return Veredicto(True)
    usadas = []
    with bd.estado() as conn:
        cur = conn.cursor()
        lista = reglas(herramienta, invitado, ahora, topes_de_hoy(cur, ahora))
        for r in lista:
            n = tomar(cur, r.clave, r.ventana, r.tope, cantidad)
            if n is None:
                conn.rollback()  # deshace los contadores ya tomados en esta llamada
                return Veredicto(False, _mensaje_agotado(r, ahora))
            usadas.append(n)
    return Veredicto(True, cupo=_cupo_buscar(usadas, lista, ahora) if herramienta in ("buscar", "tramites_buscar") else None)


def devolver(herramienta: str, invitado: str, ahora: datetime, cantidad: int = 1) -> None:
    """Devuelve unidades cuando la llamada falló por culpa del servicio (BD, Voyage), no del usuario."""
    lista = reglas(herramienta, invitado, ahora)
    if not lista:
        return
    with bd.estado() as conn:
        cur = conn.cursor()
        for r in lista:
            cur.execute("UPDATE uso SET unidades = unidades - %s WHERE clave = %s AND ventana = %s AND unidades >= %s",
                        (cantidad, r.clave, r.ventana, cantidad))


def resumen(invitado: str, ahora: datetime) -> dict:
    """Lo que le queda al invitado, en palabras y con la hora exacta de renovación (para `ayuda`)."""
    with bd.estado() as conn:
        cur = conn.cursor()
        salida = {}
        hoy = topes_de_hoy(cur, ahora)
        for herramienta in ("buscar", "ficha", "verificar_cita"):
            for r in reglas(herramienta, invitado, ahora, hoy):
                if r.global_:
                    continue
                restan = max(r.tope - _usadas(cur, r), 0)
                salida[f"{herramienta}:{r.ventana.split(':')[0]}"] = {
                    "quedan": restan, "de": r.tope, "se_renueva": hora_legible(r.renueva, ahora) + " (hora de Costa Rica)"}
    return salida
