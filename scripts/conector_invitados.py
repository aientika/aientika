"""Invitados del conector de la base: alta, baja, revocación, listado y creación de las tablas (lo corre el equipo).

    python scripts/conector_invitados.py esquema
    python scripts/conector_invitados.py alta --etiqueta "Nombre del colega"   # muestra el código UNA vez
    python scripts/conector_invitados.py listar | baja ID | revocar ID

Conexión por variables de entorno: `REPLICA_DB_HOST` (o `REPLICA_DB_INSTANCIA` desde el equipo), `REPLICA_DB_USER`,
`REPLICA_DB_PASSWORD`. Del código solo se guarda su hash; este script no imprime tokens ni hashes, y `alta` es la única vez que se ve un
código: hay que dárselo al colega en ese momento (no se puede recuperar; si se pierde, se da de baja y se crea otro).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src.agentika_contacto import contacto  # noqa: E402
from src.conector import bd, esquema_conector, invitados  # noqa: E402


def _fecha_cr(ts: int) -> str:
    """Fecha y hora de Costa Rica (UTC-6, sin horario de verano) de un timestamp."""
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts - 6 * 3600))


def main(argv: list[str] | None = None) -> int:
    """Ejecuta el subcomando pedido. Devuelve 0 si salió bien, 1 si el invitado no existe."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("esquema", help="crea las tablas del conector que falten (idempotente)")
    a = sub.add_parser("alta", help="crea un invitado y muestra su código una sola vez")
    a.add_argument("--etiqueta", required=True, help="nombre del colega, para reconocerlo en el listado")
    a.add_argument("--origen", choices=invitados.ORIGENES, default="manual", help="cómo se generó el código (por defecto, manual)")
    a.add_argument("--correo", help="correo del colega (opcional; queda para el registro por correo y las promociones)")
    a.add_argument("--promociones", action="store_true", help="el colega aceptó recibir promociones (solo con su permiso)")
    sub.add_parser("listar", help="invitados y cuántas credenciales vigentes tiene cada uno")
    sub.add_parser("promociones", help="correos de quienes aceptaron recibir promociones (para el envío)")
    c = sub.add_parser("contacto", help="agrega o cambia el correo y la autorización de promociones de un invitado")
    c.add_argument("id")
    c.add_argument("--correo")
    c.add_argument("--promociones", choices=("si", "no"), required=True)
    for nombre in ("baja", "revocar"):
        sub.add_parser(nombre, help={"baja": "desactiva y revoca sus sesiones", "revocar": "solo cierra sus sesiones"}[nombre]).add_argument("id")
    args = p.parse_args(argv)
    ahora = int(time.time())

    if args.cmd == "esquema":
        with bd.estado() as conn:
            # Postgres: también agrega a una base vieja las columnas nuevas (MIGRACIONES). SQLite (desarrollo) nace completa con el DDL.
            migrar = not bd.es_sqlite(conn)
            esquema_conector.crear_esquema(conn, migrar=migrar)
        print(f"[OK] tablas del conector verificadas{' y columnas nuevas aplicadas' if migrar else ''}")
        return 0
    with bd.estado() as conn:
        cur = conn.cursor()
        if args.cmd == "alta":
            id_, codigo = invitados.alta(cur, args.etiqueta, ahora, args.origen)
            if args.correo:
                contacto.guardar(cur, id_, args.correo, args.promociones, ahora)
            print(f"[OK] invitado {id_} creado ({args.origen}, {_fecha_cr(ahora)}). Código (se muestra UNA vez, no se guarda): {codigo}")
        elif args.cmd == "listar":
            for id_, etiqueta, activo, vigentes, creado, origen in invitados.listar(cur):
                print(f"{id_}  {_fecha_cr(creado)}  {origen or 'sin dato'}  {'activo' if activo else 'de baja'}  "
                      f"sesiones vigentes: {vigentes}  {etiqueta}")
        elif args.cmd == "baja":
            if not invitados.baja(cur, args.id, ahora):
                print(f"[ERROR] no existe el invitado {args.id}", file=sys.stderr)
                return 1
            print(f"[OK] {args.id} dado de baja; sus sesiones quedaron revocadas")
        elif args.cmd == "promociones":
            filas = contacto.promociones(cur)
            print(f"{len(filas)} invitado(s) aceptaron recibir promociones")
            for id_, etiqueta, correo_ in filas:
                print(f"{id_}  {correo_}  {etiqueta}")
        elif args.cmd == "contacto":
            if not contacto.guardar(cur, args.id, args.correo, args.promociones == "si", ahora):
                print(f"[ERROR] no existe el invitado {args.id}", file=sys.stderr)
                return 1
            print(f"[OK] {args.id}: contacto guardado (promociones: {args.promociones})")
        elif args.cmd == "revocar":
            print(f"[OK] {invitados.revocar_credenciales(cur, args.id, ahora, 'revocación manual')} sesión(es) revocada(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
