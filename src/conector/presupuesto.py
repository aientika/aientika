"""Capa gratuita dinámica: el presupuesto mensual manda.

Con `CONECTOR_PRESUPUESTO_USD` definida (valor configurable por despliegue), el tope global del día y el cupo semanal
de búsquedas por persona dejan de ser fijos:
- tope del día = (unidades del presupuesto variable del mes − unidades ya gastadas antes de hoy) / días que faltan del mes;
- cupo semanal = (tope del día × 7 × parte de `buscar`) / personas activas en los últimos 7 días, entre un piso y un techo.
Sin la variable, o si el cálculo falla, rigen los topes fijos de `limites.py` (nunca «sin tope»). Se calcula una vez por día y
proceso.
"""

from __future__ import annotations

import calendar
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta

VARIABLE_PRESUPUESTO = "CONECTOR_PRESUPUESTO_USD"
# Parte del presupuesto reservada para costos fijos; se deja un margen holgado para que no haya que recalcularla si el servicio crece.
FIJO_MENSUAL_USD = 50.0
COSTO_UNIDAD_USD = 0.001  # costo estimado por llamada (cómputo + embeddings)
PARTE_BUSCAR = 0.5  # del tope global, la mitad se asume `buscar`; el resto son fichas y verificaciones
PISO_SEMANAL, TECHO_SEMANAL = 30, 120  # límites del cupo semanal por persona
_registro = logging.getLogger(__name__)
_cache: dict[str, "Topes"] = {}


@dataclass(frozen=True)
class Topes:
    """Los topes que rigen hoy: el global del día (todas las personas) y el semanal de `buscar` (por persona)."""

    global_dia: int
    buscar_semana: int
    dinamico: bool


def presupuesto_usd() -> float | None:
    """El presupuesto mensual configurado, o None si la capa dinámica está apagada (variable sin definir o vacía)."""
    valor = os.environ.get(VARIABLE_PRESUPUESTO, "").strip()
    return float(valor) if valor else None


def calcular(presupuesto: float, gastadas_mes: int, activos: int, hoy: datetime) -> Topes:
    """Los topes de hoy a partir del presupuesto, lo gastado este mes antes de hoy y las personas activas. Puro: sin base."""
    if presupuesto <= FIJO_MENSUAL_USD:
        raise ValueError(f"el presupuesto (US${presupuesto}) no cubre lo fijo (US${FIJO_MENSUAL_USD})")
    if gastadas_mes < 0 or activos < 0:
        raise ValueError(f"datos imposibles: gastadas={gastadas_mes}, activos={activos}")
    unidades_mes = int((presupuesto - FIJO_MENSUAL_USD) / COSTO_UNIDAD_USD)
    dias_mes = calendar.monthrange(hoy.year, hoy.month)[1]
    faltan = dias_mes - hoy.day + 1
    global_dia = max(0, (unidades_mes - gastadas_mes) // faltan)
    por_persona = int(global_dia * 7 * PARTE_BUSCAR / max(activos, 1))
    return Topes(global_dia, min(TECHO_SEMANAL, max(PISO_SEMANAL, por_persona)), True)


def _gastadas_mes(cur, hoy: datetime) -> int:
    """Unidades del contador global gastadas este mes ANTES de hoy (las de hoy las controla el tope de hoy)."""
    cur.execute("SELECT COALESCE(SUM(unidades), 0) FROM uso WHERE clave = 'global' AND ventana >= %s AND ventana < %s",
                (f"dia:{hoy:%Y-%m}-01", f"dia:{hoy:%Y-%m-%d}"))
    return int(cur.fetchone()[0])


def _activos(cur, hoy: datetime) -> int:
    """Personas con al menos una llamada en los últimos 7 días (de `conector_llamada`)."""
    desde = int((hoy - timedelta(days=7)).timestamp())
    cur.execute("SELECT COUNT(DISTINCT invitado_id) FROM conector_llamada WHERE ts >= %s AND invitado_id IS NOT NULL", (desde,))
    return int(cur.fetchone()[0])


def topes(cur, hoy: datetime, fijos: Topes) -> Topes:
    """Los topes de hoy: dinámicos si hay presupuesto, si no (o si el cálculo falla) los `fijos`. Uno por día y proceso."""
    presupuesto = presupuesto_usd()
    if presupuesto is None:
        return fijos
    clave = f"{hoy:%Y-%m-%d}:{presupuesto}"
    if clave not in _cache:
        try:
            _cache.clear()
            _cache[clave] = calcular(presupuesto, _gastadas_mes(cur, hoy), _activos(cur, hoy), hoy)
            _registro.info("capa dinámica %s: %s", clave, _cache[clave])
        except Exception:  # nunca «sin tope»: ante cualquier falla, los fijos, y que se vea en el log
            _registro.exception("capa dinámica: falló el cálculo; rigen los topes fijos")
            return fijos
    return _cache[clave]
