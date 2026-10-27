"""Datos de demostración: vacía la base de datos y la llena con dos talleres de
ejemplo, su personal con acceso y un mes de trabajo.

    docker compose exec api python -m app.scripts.seed_demo
    docker compose exec api python -m app.scripts.seed_demo --purge-other-accounts

**Borra todo lo que hay.** Por eso solo corre con `DEMO_SEED_ENABLED=true`: una
instalación de verdad no la tiene y el script se niega. Sirve para probar en
desarrollo y para el despliegue de la demo, que lo ejecuta cada noche para que
cada visitante empiece desde el mismo punto.

Se puede repetir: las cuentas de SuperTokens sobreviven al vaciado (su base de
datos es otra), así que se reutilizan, se les vuelve a poner la contraseña de
la demo y se cierran sus sesiones. Con `--purge-other-accounts` (la demo
desplegada) se borran además las demás cuentas de SuperTokens: las que crean
los visitantes al aceptar invitaciones.

Los datos del taller se crean con los services de verdad, en transacciones
del taller con RLS: cumplen todas las reglas (historial, numeración,
permisos, auditoría). Después, como todo se ha creado "ahora", se mueven las
fechas hacia atrás para que la demo parezca un taller con un mes de vida: hay
órdenes paradas, cobros pendientes desde hace días y vehículos con años de
historial. Las fechas son relativas a hoy, así que la demo nunca envejece.
La auditoría se queda con la hora real: es append-only también para esto.

Las cuentas y la contraseña de la demo están en DEMO_ACCOUNTS y en
docs/guias/demo.md.
"""

import argparse
import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from supertokens_python.asyncio import (
    delete_user,
    get_users_newest_first,
    list_users_by_account_info,
)
from supertokens_python.recipe.emailpassword.asyncio import (
    sign_up,
    update_email_or_password,
)
from supertokens_python.recipe.emailpassword.interfaces import (
    SignUpOkResult,
    UpdateEmailOrPasswordOkResult,
)
from supertokens_python.recipe.session.asyncio import revoke_all_sessions_for_user
from supertokens_python.types import RecipeUserId
from supertokens_python.types.base import AccountInfoInput

from app.core import db
from app.core.config import get_settings
from app.core.supertokens import init_supertokens
from app.platform.db import platform_engine
from app.repositories import work_orders as order_repo
from app.scripts.reset_data import truncate_all
from app.services import clients as client_service
from app.services import vehicles as vehicle_service
from app.services import work_orders as order_service
from app.services import worklog as worklog_service

# Pública a propósito: es la de la demo, y se enseña en su página de acceso.
DEFAULT_PASSWORD = "demo-axtton-2026"


@dataclass(frozen=True)
class DemoAccount:
    email: str
    kind: str  # "staff" o "superadmin"


DEMO_ACCOUNTS = (
    DemoAccount("superadmin@demo.example.com", "superadmin"),
    DemoAccount("laura@demo.example.com", "staff"),
    DemoAccount("javier@demo.example.com", "staff"),
    DemoAccount("sergio@demo.example.com", "staff"),
    DemoAccount("marta@demo.example.com", "staff"),
)


# --- Cuentas -----------------------------------------------------------------


async def _account(email: str, password: str) -> str:
    """El usuario de SuperTokens de `email`, creado o reutilizado, con la
    contraseña de la demo y sin ninguna sesión abierta."""
    existing = await list_users_by_account_info("public", AccountInfoInput(email=email))
    if existing:
        user_id = existing[0].id
        result = await update_email_or_password(
            RecipeUserId(user_id), password=password, apply_password_policy=False
        )
        if not isinstance(result, UpdateEmailOrPasswordOkResult):
            raise SystemExit(f"No se pudo reutilizar {email}: {result}")
        await revoke_all_sessions_for_user(user_id)
        return user_id
    # La función de la receta, no la ruta /api/auth/signup (anulada).
    created = await sign_up("public", email, password)
    if not isinstance(created, SignUpOkResult):
        raise SystemExit(f"No se pudo crear {email}: {created.__class__.__name__}")
    return created.user.id


async def _purge_other_accounts(keep: set[str]) -> int:
    """Borra de SuperTokens toda cuenta que no sea de la demo. Solo para la demo
    desplegada: en desarrollo borraría tus cuentas de prueba."""
    to_delete: list[str] = []
    token: str | None = None
    while True:
        page = await get_users_newest_first("public", limit=100, pagination_token=token)
        to_delete += [user.id for user in page.users if user.id not in keep]
        token = page.next_pagination_token
        if token is None:
            break
    for user_id in to_delete:
        await delete_user(user_id)
    return len(to_delete)


# --- Lo que se va creando ----------------------------------------------------


@dataclass
class Shop:
    """Un taller de la demo mientras se llena."""

    id: UUID
    # Ficha (employee_id) y usuario (user_id) de quien hace cada cosa.
    staff: dict[str, tuple[UUID, UUID | None]] = field(default_factory=dict)
    clients: dict[str, UUID] = field(default_factory=dict)
    vehicles: dict[str, UUID] = field(default_factory=dict)
    # Hace cuántos días empezó cada periodo de titularidad, en orden.
    ownerships: list[tuple[UUID, UUID, int]] = field(default_factory=list)
    # Hace cuántos días se abrió y se tocó por última vez cada orden.
    order_days: list[tuple[UUID, int, int]] = field(default_factory=list)

    def employee(self, key: str) -> UUID:
        return self.staff[key][0]

    def user(self, key: str) -> UUID:
        user_id = self.staff[key][1]
        assert user_id is not None, f"{key} no tiene acceso"
        return user_id


async def _platform_rows(
    accounts: dict[str, str],
) -> tuple[Shop, Shop]:
    """Usuarios, talleres y fichas del personal: lo que es de la plataforma, con
    su rol. El resto se crea dentro de cada taller, con RLS."""
    async with platform_engine.begin() as conn:
        users: dict[str, UUID] = {}
        for account in DEMO_ACCOUNTS:
            users[account.email] = await conn.scalar(
                text(
                    "INSERT INTO users (supertokens_user_id, kind) VALUES (:s, :k)"
                    " RETURNING id"
                ),
                {"s": accounts[account.email], "k": account.kind},
            )
        superadmin = users["superadmin@demo.example.com"]
        await conn.execute(
            text(
                "INSERT INTO audit_log (actor_user_id, action, target_type)"
                " VALUES (:u, 'superadmin_created', 'user')"
            ),
            {"u": superadmin},
        )

        async def workshop(name: str, **legal: str) -> Shop:
            workshop_id = await conn.scalar(
                text(
                    "INSERT INTO workshops (name, legal_name, tax_id, address, phone)"
                    " VALUES (:n, :ln, :t, :a, :p) RETURNING id"
                ),
                {"n": name, **legal},
            )
            await conn.execute(
                text(
                    "INSERT INTO audit_log (actor_user_id, action, target_type,"
                    " target_id, details)"
                    " VALUES (:u, 'workshop_created', 'workshop', :w,"
                    " jsonb_build_object('name', CAST(:n AS text)))"
                ),
                {"u": superadmin, "w": workshop_id, "n": name},
            )
            return Shop(workshop_id)

        async def employee(
            shop: Shop,
            key: str,
            name: str,
            role: str,
            position: str,
            cost_cents: int,
            email: str | None,
        ) -> None:
            employee_id = await conn.scalar(
                text(
                    "INSERT INTO employees"
                    " (workshop_id, user_id, name, role, position, hourly_cost_cents)"
                    " VALUES (:w, :u, :n, :r, :p, :c) RETURNING id"
                ),
                {
                    "w": shop.id,
                    "u": users[email] if email else None,
                    "n": name,
                    "r": role,
                    "p": position,
                    "c": cost_cents,
                },
            )
            shop.staff[key] = (employee_id, users[email] if email else None)

        main = await workshop(
            "Talleres Martínez",
            ln="Talleres Martínez e Hijos, S.L.",
            t="B02123456",
            a="Calle de la Industria 14, 02006 Albacete",
            p="967 21 43 65",
        )
        await employee(
            main,
            "laura",
            "Laura Martínez",
            "admin",
            "Gerente",
            2800,
            "laura@demo.example.com",
        )
        await employee(
            main,
            "javier",
            "Javier Ruiz",
            "mechanic",
            "Jefe de taller",
            2200,
            "javier@demo.example.com",
        )
        await employee(
            main,
            "sergio",
            "Sergio Gómez",
            "mechanic",
            "Electromecánico",
            1900,
            "sergio@demo.example.com",
        )
        # Sin acceso a la aplicación: existe igual, y otros anotan su trabajo.
        await employee(
            main, "pedro", "Pedro Ortega", "mechanic", "Aprendiz", 1300, None
        )

        small = await workshop(
            "Taller Rápido Levante",
            ln="Rápido Levante, S.L.U.",
            t="B46987654",
            a="Avenida del Puerto 210, 46023 Valencia",
            p="963 33 21 00",
        )
        # Laura también administra este: así se ve el selector de talleres.
        await employee(
            small,
            "laura",
            "Laura Martínez",
            "admin",
            "Gerente",
            2800,
            "laura@demo.example.com",
        )
        await employee(
            small,
            "marta",
            "Marta Soler",
            "mechanic",
            "Mecánica",
            2000,
            "marta@demo.example.com",
        )
    return main, small


# --- El trabajo de un taller -------------------------------------------------


Step = Callable[[AsyncSession, UUID], Awaitable[None]]


async def _version(session: AsyncSession, order_id: UUID) -> int:
    order = await order_repo.get(session, order_id)
    assert order is not None
    return order.version


class Builder:
    """Crea clientes, vehículos y órdenes de un taller con los services."""

    def __init__(self, session: AsyncSession, shop: Shop) -> None:
        self.session = session
        self.shop = shop
        self.today = date.today()

    async def client(self, key: str, **fields: Any) -> None:
        self.shop.clients[key] = await client_service.create_client(
            self.session, self.shop.id, fields
        )

    async def vehicle(
        self, key: str, owners: list[tuple[str, int]], **fields: Any
    ) -> None:
        """`owners`: los titulares en orden, con hace cuántos días empezó cada uno."""
        (first, since), *later = owners
        vehicle_id = await vehicle_service.create_vehicle(
            self.session, self.shop.id, fields, self.shop.clients[first]
        )
        self.shop.vehicles[key] = vehicle_id
        self.shop.ownerships.append((vehicle_id, self.shop.clients[first], since))
        for owner, since in later:
            vehicle = await vehicle_service.get_vehicle(self.session, vehicle_id)
            await vehicle_service.change_owner(
                self.session,
                self.shop.id,
                self.shop.user("laura"),
                vehicle_id,
                expected_version=vehicle.vehicle.version,
                client_id=self.shop.clients[owner],
            )
            self.shop.ownerships.append((vehicle_id, self.shop.clients[owner], since))

    async def order(
        self,
        vehicle: str,
        *,
        opened: int,
        last: int,
        type_: str = "breakdown",
        warranty_of: UUID | None = None,
        steps: tuple[Step, ...] = (),
        **fields: Any,
    ) -> UUID:
        """Abre una orden y le aplica `steps` en orden. `opened` y `last` son
        hace cuántos días se abrió y se tocó por última vez."""
        order = await order_service.open_order(
            self.session,
            self.shop.id,
            self.shop.employee("laura"),
            vehicle_id=self.shop.vehicles[vehicle],
            type_=type_,
            warranty_of_id=warranty_of,
            fields=fields,
        )
        for step in steps:
            await step(self.session, order.id)
        self.shop.order_days.append((order.id, opened, last))
        return order.id

    # Los pasos, para componer el ciclo de vida de cada orden.

    def move(self, to: str, note: str | None = None, by: str = "laura") -> Step:
        async def step(session: AsyncSession, order_id: UUID) -> None:
            await order_service.change_status(
                session,
                order_id,
                self.shop.employee(by),
                "admin" if by == "laura" else "mechanic",
                expected_version=await _version(session, order_id),
                to_status=to,
                note=note,
            )

        return step

    def no_quote(self, reason: str) -> Step:
        async def step(session: AsyncSession, order_id: UUID) -> None:
            await order_service.set_no_quote(
                session,
                self.shop.id,
                self.shop.user("laura"),
                order_id,
                expected_version=await _version(session, order_id),
                reason=reason,
            )

        return step

    def diagnose(self, by: str, *texts: str) -> Step:
        """Una o varias versiones del diagnóstico, cada una sobre la anterior."""

        async def step(session: AsyncSession, order_id: UUID) -> None:
            for number, text_ in enumerate(texts):
                await worklog_service.save_diagnosis(
                    session,
                    self.shop.id,
                    self.shop.employee(by),
                    order_id,
                    base_version_no=number,
                    text=text_,
                )

        return step

    def note(self, by: str, body: str) -> Step:
        async def step(session: AsyncSession, order_id: UUID) -> None:
            await worklog_service.add_note(
                session, self.shop.id, self.shop.employee(by), order_id, body=body
            )

        return step

    def work(
        self,
        who: str,
        description: str,
        days_ago: int,
        hours: str | None,
        recorder: str | None = None,
        voided: bool = False,
    ) -> Step:
        async def step(session: AsyncSession, order_id: UUID) -> None:
            from decimal import Decimal

            recorded_by = recorder or who
            entry_id = await worklog_service.add_work_entry(
                session,
                self.shop.id,
                self.shop.employee(recorded_by),
                order_id,
                employee_id=self.shop.employee(who),
                description=description,
                worked_on=self.today - timedelta(days=days_ago),
                hours=Decimal(hours) if hours else None,
            )
            if voided:
                await worklog_service.void_work_entry(
                    session,
                    self.shop.employee(recorded_by),
                    "admin" if recorded_by == "laura" else "mechanic",
                    order_id,
                    entry_id,
                )

        return step

    def pay(
        self,
        status: str,
        method: str | None = None,
        euros: int | None = None,
        days_ago: int = 0,
    ) -> Step:
        async def step(session: AsyncSession, order_id: UUID) -> None:
            await order_service.record_payment(
                session,
                self.shop.id,
                self.shop.user("laura"),
                order_id,
                expected_version=await _version(session, order_id),
                status=status,
                method=method,
                amount_cents=euros * 100 if euros else None,
                paid_on=self.today - timedelta(days=days_ago) if euros else None,
            )

        return step


async def _main_workshop(b: Builder) -> None:
    """Talleres Martínez: un mes de trabajo con órdenes en cada estado posible
    sin presupuestos (los presupuestos llegan en F3)."""
    await b.client(
        "carmen",
        name="Carmen López Gil",
        phone="600 112 233",
        email="carmen.lopez@demo.example.com",
        tax_id="44556677B",
        address="Calle Tinte 22, 3.º B, Albacete",
    )
    await b.client(
        "antonio",
        name="Antonio García Pérez",
        phone="611 223 344",
        notes="Prefiere que le llamen a partir de las 17:00.",
    )
    await b.client(
        "lucia",
        name="Lucía Fernández",
        phone="622 334 455",
        email="lucia.fernandez@demo.example.com",
        language="en",
        notes="Habla mejor inglés: los avisos, en inglés.",
    )
    await b.client(
        "transportes",
        kind="company",
        name="Transportes Hermanos Navarro, S.L.",
        phone="967 55 66 77",
        email="flota@demo.example.com",
        tax_id="B02987123",
        address="Polígono Campollano, calle E, 8, Albacete",
        notes="Flota de furgonetas. Facturan a 30 días.",
    )
    await b.client("jose", name="José María Sánchez", phone="633 445 566")
    await b.client(
        "elena",
        name="Elena Romero Castillo",
        phone="644 556 677",
        email="elena.romero@demo.example.com",
    )
    await b.client("miguel", name="Miguel Ángel Torres", phone="655 667 788")
    await b.client(
        "autoescuela",
        kind="company",
        name="Autoescuela La Mancha",
        phone="967 11 22 33",
        email="info@autoescuela.demo.example.com",
        tax_id="B02445566",
    )
    await b.client("rosa", name="Rosa Martín Herrera", phone="666 778 899")
    await b.client(
        "pablo",
        name="Pablo Jiménez",
        phone="677 889 900",
        email="pablo.jimenez@demo.example.com",
    )
    # La que pedirá que se borren sus datos (RF-15).
    await b.client(
        "irene",
        name="Irene Moreno Díaz",
        phone="688 990 011",
        email="irene.moreno@demo.example.com",
        address="Calle Mayor 5, Albacete",
    )
    # Archivada: dejó de venir.
    await b.client("ramon", name="Ramón Castro", phone="699 001 122")

    await b.vehicle(
        "ibiza",
        [("carmen", 900)],
        plate="4821 KLM",
        make="Seat",
        model="Ibiza",
        year=2018,
        fuel="gasoline",
        vin="VSSZZZ6JZJR123456",
    )
    await b.vehicle(
        "corolla",
        [("antonio", 700)],
        plate="7392 LBC",
        make="Toyota",
        model="Corolla",
        year=2020,
        fuel="hybrid",
    )
    await b.vehicle(
        "golf",
        [("lucia", 400)],
        plate="2276 JTR",
        make="Volkswagen",
        model="Golf",
        year=2015,
        fuel="diesel",
    )
    await b.vehicle(
        "transit1",
        [("transportes", 1200)],
        plate="1123 HFG",
        make="Ford",
        model="Transit Custom",
        year=2017,
        fuel="diesel",
    )
    await b.vehicle(
        "transit2",
        [("transportes", 800)],
        plate="5590 KDS",
        make="Ford",
        model="Transit",
        year=2019,
        fuel="diesel",
    )
    # Cambió de manos: era de José y se lo vendió a Elena hace un mes (RF-12).
    await b.vehicle(
        "clio",
        [("jose", 1500), ("elena", 30)],
        plate="9014 GZX",
        make="Renault",
        model="Clio",
        year=2012,
        fuel="gasoline",
    )
    await b.vehicle(
        "model3",
        [("miguel", 250)],
        plate="3348 MDP",
        make="Tesla",
        model="Model 3",
        year=2022,
        fuel="electric",
    )
    await b.vehicle(
        "leon",
        [("autoescuela", 600)],
        plate="6671 LRW",
        make="Seat",
        model="León",
        year=2021,
        fuel="gasoline",
    )
    await b.vehicle(
        "c3",
        [("rosa", 1000)],
        plate="0457 HPN",
        make="Citroën",
        model="C3",
        year=2016,
        fuel="gasoline",
    )
    await b.vehicle(
        "qashqai",
        [("pablo", 500)],
        plate="8803 KXC",
        make="Nissan",
        model="Qashqai",
        year=2019,
        fuel="diesel",
    )
    await b.vehicle(
        "fiesta",
        [("irene", 650)],
        plate="1975 JBM",
        make="Ford",
        model="Fiesta",
        year=2014,
        fuel="gasoline",
    )
    await b.vehicle(
        "megane",
        [("ramon", 1800)],
        plate="2209 DFK",
        make="Renault",
        model="Mégane",
        year=2006,
        fuel="diesel",
    )

    # Recibida hoy, sin tocar: la que acaba de llegar al mostrador.
    await b.order(
        "corolla",
        opened=0,
        last=0,
        type_="maintenance",
        reason="Revisión de los 60.000 km y cambio de aceite.",
        odometer_km=58350,
        expected_delivery_at=_at(b.today, 1, 13),
        responsible_employee_id=b.shop.employee("sergio"),
    )
    # En diagnóstico, parada hace días: sale primero en "las más paradas".
    await b.order(
        "golf",
        opened=6,
        last=5,
        reason="Humo blanco al arrancar en frío y pierde potencia.",
        odometer_km=187410,
        responsible_employee_id=b.shop.employee("javier"),
        steps=(
            b.move("diagnosing"),
            b.note(
                "javier", "Huele a refrigerante en el escape. Sospecho junta de culata."
            ),
            b.work(
                "javier",
                "Prueba de estanqueidad del circuito de refrigeración",
                5,
                "1.0",
            ),
            b.note("laura", "La clienta pide que la llamemos antes de desmontar nada."),
        ),
    )
    # En reparación sin presupuesto: precio cerrado (RF-27).
    await b.order(
        "ibiza",
        opened=3,
        last=1,
        type_="maintenance",
        reason="Cambio de distribución (precio cerrado acordado: 420 €).",
        odometer_km=96520,
        dropped_off_by_name="Andrés López",
        dropped_off_by_phone="600 998 877",
        responsible_employee_id=b.shop.employee("sergio"),
        expected_delivery_at=_at(b.today, 1, 18),
        steps=(
            b.no_quote("fixed_price"),
            b.move("in_repair", by="sergio"),
            b.work(
                "sergio", "Desmontaje y sustitución del kit de distribución", 1, "3.5"
            ),
            b.work(
                "pedro", "Cambio de líquido refrigerante", 1, "0.5", recorder="sergio"
            ),
            b.diagnose(
                "sergio",
                "Se sustituye la correa de distribución, tensor, rodillos y bomba de agua, "
                "según el mantenimiento del fabricante.",
            ),
        ),
    )
    # Esperando piezas, con un trabajo anotado por error y anulado.
    await b.order(
        "transit1",
        opened=9,
        last=4,
        reason="Ruido metálico en la caja de cambios al meter segunda.",
        odometer_km=244050,
        responsible_employee_id=b.shop.employee("javier"),
        steps=(
            b.move("diagnosing"),
            b.diagnose(
                "javier",
                "El sincronizador de segunda está desgastado.",
                "El sincronizador de segunda está desgastado y hay holgura en el "
                "rodamiento del primario. Hay que abrir la caja de cambios.",
            ),
            b.no_quote("fixed_price"),
            b.move("in_repair", by="javier"),
            b.work("javier", "Desmontaje de la caja de cambios", 6, "4.0"),
            b.work("sergio", "Desmontaje de la caja de cambios", 6, "4.0", voided=True),
            b.move("waiting_parts", by="javier"),
            b.note("laura", "Piezas pedidas a Recambios Albacete. Llegan el jueves."),
        ),
    )
    # Garantía de una reparación anterior: original entregada y cobrada.
    original = await b.order(
        "leon",
        opened=40,
        last=33,
        reason="Cambio de embrague: patina en marchas largas.",
        odometer_km=86900,
        responsible_employee_id=b.shop.employee("javier"),
        steps=(
            b.move("diagnosing"),
            b.diagnose("javier", "Embrague desgastado. Se sustituye el kit completo."),
            b.no_quote("fixed_price"),
            b.move("in_repair", by="javier"),
            b.work(
                "javier", "Sustitución del kit de embrague y volante bimasa", 36, "6.0"
            ),
            b.move("ready", by="javier"),
            b.move("delivered"),
            b.pay("paid", "transfer", 890, days_ago=30),
        ),
    )
    await b.order(
        "leon",
        opened=2,
        last=1,
        type_="warranty",
        warranty_of=original,
        reason="Vuelve a oírse un ruido al pisar el embrague.",
        odometer_km=88150,
        responsible_employee_id=b.shop.employee("javier"),
        steps=(
            b.no_quote("warranty"),
            b.move("in_repair", by="javier"),
            b.work("javier", "Ajuste del cojinete de empuje", 1, "1.5"),
        ),
    )
    # Lista para recoger.
    await b.order(
        "model3",
        opened=4,
        last=0,
        reason="Avisos intermitentes del sensor de presión de neumáticos.",
        odometer_km=41300,
        responsible_employee_id=b.shop.employee("sergio"),
        steps=(
            b.move("diagnosing"),
            b.diagnose(
                "sergio",
                "Un sensor de presión de la rueda trasera izquierda tenía la pila "
                "agotada. Se sustituye y se vuelven a programar los cuatro.",
            ),
            b.no_quote("fixed_price"),
            b.move("in_repair", by="sergio"),
            b.work("sergio", "Sustitución y programación del sensor TPMS", 0, "1.0"),
            b.move("ready", by="sergio"),
        ),
    )
    # Lista sin reparar: el diagnóstico no encontró nada.
    await b.order(
        "c3",
        opened=3,
        last=2,
        reason="Vibración en el volante a más de 100 km/h.",
        odometer_km=101620,
        steps=(
            b.move("diagnosing"),
            b.work("sergio", "Prueba en carretera y equilibrado de ruedas", 2, "0.75"),
            b.move(
                "ready",
                note="Se equilibran las ruedas y la vibración desaparece. No hay avería.",
            ),
        ),
    )
    # Entregadas pendientes de cobro (RF-29), una de hace casi tres semanas.
    await b.order(
        "transit2",
        opened=24,
        last=19,
        reason="Revisión anual de la flota.",
        type_="maintenance",
        odometer_km=165500,
        steps=(
            b.no_quote("fixed_price"),
            b.move("in_repair", by="javier"),
            b.work("javier", "Revisión completa, filtros y aceite", 21, "2.5"),
            b.move("ready", by="javier"),
            b.move("delivered"),
            b.note(
                "laura", "Transportes Navarro paga a 30 días: reclamar a fin de mes."
            ),
        ),
    )
    await b.order(
        "qashqai",
        opened=7,
        last=3,
        reason="La batería se descarga si está dos días parado.",
        odometer_km=119800,
        steps=(
            b.move("diagnosing"),
            b.diagnose(
                "sergio",
                "El módulo del portón trasero consume corriente con el coche apagado. "
                "Se sustituye.",
            ),
            b.no_quote("fixed_price"),
            b.move("in_repair", by="sergio"),
            b.work("sergio", "Medición de consumo en reposo", 5, "1.5"),
            b.work("sergio", "Sustitución del módulo del portón", 4, "1.0"),
            b.move("ready", by="sergio"),
            b.move("delivered"),
        ),
    )
    # Entregadas y cobradas, de cada forma de pago.
    await b.order(
        "clio",
        opened=12,
        last=10,
        type_="itv",
        reason="Preparar la ITV: luces y frenos.",
        odometer_km=142900,
        steps=(
            b.no_quote("fixed_price"),
            b.move("in_repair", by="sergio"),
            b.work(
                "sergio", "Revisión de luces y sustitución de dos lámparas", 11, "0.5"
            ),
            b.move("ready", by="sergio"),
            b.move("delivered"),
            b.pay("paid", "card", 65, days_ago=10),
        ),
    )
    await b.order(
        "corolla",
        opened=200,
        last=195,
        type_="maintenance",
        reason="Revisión de los 45.000 km.",
        odometer_km=45100,
        steps=(
            b.no_quote("fixed_price"),
            b.move("in_repair", by="sergio"),
            b.work("sergio", "Revisión de mantenimiento", 196, "1.5"),
            b.move("ready", by="sergio"),
            b.move("delivered"),
            b.pay("paid", "cash", 180, days_ago=195),
        ),
    )
    # Sin cargo: un diagnóstico que el taller no cobra.
    await b.order(
        "golf",
        opened=60,
        last=58,
        reason="Testigo de motor encendido.",
        odometer_km=185900,
        steps=(
            b.move("diagnosing"),
            b.work("javier", "Lectura de averías con la máquina", 59, "0.5"),
            b.move(
                "ready", note="Sensor de temperatura exterior suelto: se reconecta."
            ),
            b.move("delivered"),
            b.pay("no_charge"),
        ),
    )
    # Cancelada: abierta por error.
    await b.order(
        "ibiza",
        opened=15,
        last=15,
        reason="Duplicada.",
        steps=(b.move("cancelled", note="Abierta por error: era la misma visita."),),
    )
    # Irene: una orden entregada y cobrada, y después pide que se borren sus datos.
    await b.order(
        "fiesta",
        opened=90,
        last=85,
        reason="Cambio de pastillas de freno delanteras.",
        odometer_km=132100,
        dropped_off_by_name="Su padre, Luis Moreno",
        dropped_off_by_phone="688 111 222",
        steps=(
            b.no_quote("fixed_price"),
            b.move("in_repair", by="javier"),
            b.work("javier", "Sustitución de pastillas y discos delanteros", 86, "1.5"),
            b.move("ready", by="javier"),
            b.move("delivered"),
            b.pay("paid", "card", 210, days_ago=85),
        ),
    )
    irene = await client_service.get_client(b.session, b.shop.clients["irene"])
    await client_service.anonymize_client(
        b.session,
        b.shop.id,
        b.shop.user("laura"),
        irene.id,
        expected_version=irene.version,
    )
    ramon = await client_service.get_client(b.session, b.shop.clients["ramon"])
    await client_service.set_archived(
        b.session, ramon.id, expected_version=ramon.version, archived=True
    )


async def _small_workshop(b: Builder) -> None:
    """Taller Rápido Levante: poco, para que se note al cambiar de taller."""
    await b.client(
        "vicente",
        name="Vicente Ferrer Climent",
        phone="610 203 040",
        email="vicente.ferrer@demo.example.com",
    )
    await b.client("amparo", name="Amparo Llopis", phone="620 304 050")
    await b.vehicle(
        "panda",
        [("vicente", 300)],
        plate="5512 LKP",
        make="Fiat",
        model="Panda",
        year=2019,
        fuel="gasoline",
    )
    await b.vehicle(
        "i30",
        [("amparo", 700)],
        plate="0788 KJH",
        make="Hyundai",
        model="i30",
        year=2017,
        fuel="diesel",
    )
    await b.order(
        "panda",
        opened=1,
        last=0,
        type_="maintenance",
        reason="Cambio de neumáticos delanteros.",
        responsible_employee_id=b.shop.employee("marta"),
        steps=(
            b.no_quote("fixed_price"),
            b.move("in_repair", by="marta"),
            b.work("marta", "Montaje y equilibrado de dos neumáticos", 0, "0.75"),
        ),
    )
    await b.order(
        "i30",
        opened=5,
        last=4,
        reason="Ruido en la suspensión delantera.",
        steps=(
            b.move("diagnosing"),
            b.diagnose("marta", "Bieleta de la barra estabilizadora rota."),
            b.no_quote("fixed_price"),
            b.move("in_repair", by="marta"),
            b.move("ready", by="marta"),
            b.move("delivered"),
        ),
    )


def _at(today: date, days: int, hour: int) -> datetime:
    """Una hora en Madrid dentro de `days` días, para la entrega prevista."""
    from zoneinfo import ZoneInfo

    moment = datetime.combine(today + timedelta(days=days), datetime.min.time())
    return moment.replace(hour=hour, tzinfo=ZoneInfo("Europe/Madrid"))


async def _fill(shop: Shop, build: Callable[[Builder], Awaitable[None]]) -> None:
    async with db.workshop_transaction([shop.id]) as session:
        await build(Builder(session, shop))


# --- Fechas hacia atrás ------------------------------------------------------


async def _backdate(shops: tuple[Shop, ...]) -> None:
    """Todo se creó "ahora": se reparte hacia atrás, relativo a hoy.

    Con el rol de plataforma (BYPASSRLS, y UPDATE sobre estas tablas) para las
    órdenes, sus historiales, clientes y vehículos. Los periodos de titularidad
    los congela un trigger con cualquier rol, así que esos van con el dueño, que
    lo desactiva dentro de su transacción (y vuelve a activarlo antes de
    confirmar).
    """
    async with platform_engine.begin() as conn:
        for shop in shops:
            for order_id, opened, last in shop.order_days:
                await _backdate_order(conn, order_id, opened, last)
            await _renumber(conn, shop.id)
            await conn.execute(
                text(
                    "UPDATE clients SET created_at = clock_timestamp() - interval '2 years'"
                    " WHERE workshop_id = :w AND anonymized_at IS NULL"
                ),
                {"w": shop.id},
            )

    owner = create_async_engine(os.environ["MIGRATIONS_DATABASE_URL"])
    try:
        async with owner.begin() as conn:
            # El dueño también pasa por RLS (FORCE): fija los talleres.
            await conn.execute(
                text("SELECT set_config('app.workshop_ids', :ids, true)"),
                {"ids": "{" + ",".join(str(s.id) for s in shops) + "}"},
            )
            await conn.execute(
                text(
                    "ALTER TABLE vehicle_ownerships"
                    " DISABLE TRIGGER vehicle_ownerships_closed_frozen"
                )
            )
            for shop in shops:
                await _backdate_ownerships(conn, shop)
            await conn.execute(
                text(
                    "ALTER TABLE vehicle_ownerships"
                    " ENABLE TRIGGER vehicle_ownerships_closed_frozen"
                )
            )
    finally:
        await owner.dispose()


async def _backdate_order(conn: Any, order_id: UUID, opened: int, last: int) -> None:
    """Los cambios de estado, repartidos entre `opened` y `last` días atrás; lo
    escrito en la orden, entre medias; y la orden, con sus fechas sacadas de su
    historial (la entrega es el cambio a `delivered`)."""
    params = {"o": order_id, "open": opened, "last": last}
    await conn.execute(
        text(
            "WITH ranked AS ("
            " SELECT id, row_number() OVER (ORDER BY seq) - 1 AS i,"
            " count(*) OVER () AS n"
            " FROM work_order_status_changes WHERE work_order_id = :o)"
            " UPDATE work_order_status_changes c SET created_at = clock_timestamp()"
            " - make_interval(secs => 86400 * (CAST(:open AS float)"
            " - (CAST(:open AS float) - CAST(:last AS float))"
            " * CASE WHEN r.n = 1 THEN 0 ELSE r.i::float / (r.n - 1) END))"
            " - make_interval(hours => 2)"
            " FROM ranked r WHERE c.id = r.id"
        ),
        params,
    )
    middle = (opened + last) / 2
    # work_entries no: su trigger solo deja escribir la anulación, con cualquier
    # rol. Su fecha de trabajo (`worked_on`) ya se puso al anotarlo.
    for table in ("diagnosis_versions", "internal_notes"):
        await conn.execute(
            text(
                f"UPDATE {table} SET created_at = created_at"
                " - make_interval(secs => 86400 * CAST(:d AS float))"
                " WHERE work_order_id = :o"
            ),
            {"o": order_id, "d": middle},
        )
    await conn.execute(
        text(
            "UPDATE work_orders o SET"
            " created_at = h.first, last_activity_at = h.last,"
            " delivered_at = CASE WHEN o.status = 'delivered' THEN h.delivered END"
            " FROM (SELECT min(created_at) AS first, max(created_at) AS last,"
            "  max(created_at) FILTER (WHERE to_status = 'delivered') AS delivered"
            "  FROM work_order_status_changes WHERE work_order_id = :o) h"
            " WHERE o.id = :o"
        ),
        {"o": order_id},
    )


async def _renumber(conn: Any, workshop_id: UUID) -> None:
    """Los números, en el orden de las fechas ya movidas: el script abre las
    órdenes en el orden que le conviene, no en el del calendario, y una orden de
    abril no puede ser la 12 si la de hoy es la 1. El año sale de la fecha en la
    zona del taller (como order_repo.local_year), y los contadores se rehacen con
    el último número de cada año, para que la siguiente orden siga la serie."""
    params = {"w": workshop_id}
    # En dos pasadas: renumerar en el sitio chocaría con el índice único.
    await conn.execute(
        text("UPDATE work_orders SET number = number + 100000 WHERE workshop_id = :w"),
        params,
    )
    await conn.execute(
        text(
            "WITH dated AS ("
            " SELECT o.id, extract(year FROM o.created_at AT TIME ZONE w.timezone)::int"
            " AS year FROM work_orders o JOIN workshops w ON w.id = o.workshop_id"
            " WHERE o.workshop_id = :w),"
            " ranked AS (SELECT d.id, d.year, row_number() OVER"
            " (PARTITION BY d.year ORDER BY o.created_at, o.id) AS number"
            " FROM dated d JOIN work_orders o ON o.id = d.id)"
            " UPDATE work_orders o SET year = r.year, number = r.number"
            " FROM ranked r WHERE o.id = r.id"
        ),
        params,
    )
    await conn.execute(
        text("DELETE FROM work_order_counters WHERE workshop_id = :w"), params
    )
    await conn.execute(
        text(
            "INSERT INTO work_order_counters (workshop_id, year, last_number)"
            " SELECT workshop_id, year, max(number) FROM work_orders"
            " WHERE workshop_id = :w GROUP BY workshop_id, year"
        ),
        params,
    )


async def _backdate_ownerships(conn: Any, shop: Shop) -> None:
    """Cada periodo empieza cuando dice la demo y el anterior acaba entonces. Del
    más antiguo al más nuevo: así nunca se solapan dos a medio mover (EXCLUDE)."""
    by_vehicle: dict[UUID, list[tuple[UUID, int]]] = {}
    for vehicle_id, client_id, since in shop.ownerships:
        by_vehicle.setdefault(vehicle_id, []).append((client_id, since))
    for vehicle_id, periods in by_vehicle.items():
        for index, (client_id, since) in enumerate(periods):
            until = periods[index + 1][1] if index + 1 < len(periods) else None
            await conn.execute(
                text(
                    "UPDATE vehicle_ownerships SET"
                    " started_at = clock_timestamp() - make_interval(days => :s),"
                    " ended_at = CASE WHEN CAST(:u AS int) IS NULL THEN NULL"
                    "  ELSE clock_timestamp() - make_interval(days => CAST(:u AS int))"
                    "  END"
                    " WHERE vehicle_id = :v AND client_id = :c"
                ),
                {"v": vehicle_id, "c": client_id, "s": since, "u": until},
            )
        await conn.execute(
            text(
                "UPDATE vehicles SET created_at = clock_timestamp()"
                " - make_interval(days => :s) WHERE id = :v"
            ),
            {"v": vehicle_id, "s": periods[0][1]},
        )


# --- Entrada -----------------------------------------------------------------


async def seed_demo(*, password: str, purge_other_accounts: bool = False) -> None:
    init_supertokens()
    await truncate_all()
    accounts = {a.email: await _account(a.email, password) for a in DEMO_ACCOUNTS}
    if purge_other_accounts:
        purged = await _purge_other_accounts(set(accounts.values()))
        print(f"Cuentas ajenas a la demo borradas: {purged}")
    main, small = await _platform_rows(accounts)
    await _fill(main, _main_workshop)
    await _fill(small, _small_workshop)
    await _backdate((main, small))
    print("Datos de demostración listos: Talleres Martínez y Taller Rápido Levante.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--purge-other-accounts",
        action="store_true",
        help="borra de SuperTokens las cuentas que no son de la demo",
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    if not settings.demo_seed_enabled:
        raise SystemExit(
            "Este script BORRA todos los datos. Solo corre con DEMO_SEED_ENABLED=true"
            " (desarrollo o el despliegue de la demo, nunca una instalación real)."
        )

    async def run() -> None:
        try:
            await seed_demo(
                password=settings.demo_password or DEFAULT_PASSWORD,
                purge_other_accounts=args.purge_other_accounts,
            )
        finally:
            await db.engine.dispose()
            await platform_engine.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
