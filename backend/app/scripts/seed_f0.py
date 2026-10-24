"""Datos de prueba de F0: dos talleres, cada uno con un cliente, un vehículo y una orden.

    docker compose exec api python -m app.scripts.seed_f0

Borra todos los datos antes (reset_data) y usa la conexión de plataforma porque
crea datos de varios talleres a la vez: con axtton_app, la política de RLS lo
impediría (WITH CHECK).
"""

import asyncio

from sqlalchemy import text

from app.platform.db import PlatformSessionFactory, platform_engine
from app.scripts.reset_data import truncate_all

WORKSHOPS = [
    ("Talleres Pérez", "Ana López", "1234ABC"),
    ("Taller Norte", "Luis García", "5678DEF"),
]


async def main() -> None:
    await truncate_all()
    async with PlatformSessionFactory() as session, session.begin():
        for workshop_name, client_name, plate in WORKSHOPS:
            workshop_id = await session.scalar(
                text("INSERT INTO workshops (name) VALUES (:n) RETURNING id"),
                {"n": workshop_name},
            )
            client_id = await session.scalar(
                text(
                    "INSERT INTO clients (workshop_id, name) VALUES (:w, :n) RETURNING id"
                ),
                {"w": workshop_id, "n": client_name},
            )
            vehicle_id = await session.scalar(
                text(
                    "INSERT INTO vehicles (workshop_id, plate) VALUES (:w, :p) RETURNING id"
                ),
                {"w": workshop_id, "p": plate},
            )
            work_order_id = await session.scalar(
                text(
                    "INSERT INTO work_orders (workshop_id, vehicle_id, client_id)"
                    " VALUES (:w, :v, :c) RETURNING id"
                ),
                {"w": workshop_id, "v": vehicle_id, "c": client_id},
            )
            print(f"{workshop_name}: taller {workshop_id} · orden {work_order_id}")
    await platform_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
