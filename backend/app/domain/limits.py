"""Los límites de recursos de un taller (especificación §10, RF-114).

Cada taller nace con los del plan básico y el superadministrador los ajusta
taller a taller. Los planes con nombre (básico, profesional…) son para cuando haya
facturación: entonces estos valores serán los del básico, sin cambiar cómo se
aplican.

Sin I/O: qué se limita, cuánto y con qué error. Contar y aplicar lo hacen
repositories/limits.py y services/limits.py.
"""

from enum import StrEnum


class Resource(StrEnum):
    # Personas que pueden entrar (F1). Las fichas sin acceso no cuentan aquí.
    EMPLOYEES_WITH_ACCESS = "employees_with_access"
    # Fichas activas, con o sin acceso: un mecánico que no entra también cuenta.
    EMPLOYEES = "employees"
    # Acumulados: archivados y anonimizados ocupan su fila igual. Si archivar
    # liberase hueco, archivar y desarchivar serviría para saltarse el límite.
    CLIENTS = "clients"
    VEHICLES = "vehicles"
    # Las órdenes se acumulan sin fin: se limitan por mes, el del taller.
    ORDERS_PER_MONTH = "orders_per_month"


def limit_column(resource: Resource) -> str:
    """La columna de `workshops` que guarda el límite: max_<recurso>."""
    return f"max_{resource.value}"


# Un taller pequeño: de 1 a 5 mecánicos y unas 5 a 8 órdenes al día.
BASIC_PLAN: dict[Resource, int] = {
    Resource.EMPLOYEES_WITH_ACCESS: 5,
    Resource.EMPLOYEES: 10,
    Resource.CLIENTS: 1000,
    Resource.VEHICLES: 1500,
    Resource.ORDERS_PER_MONTH: 200,
}

# La demo pública (app/scripts/seed_demo.py): basta para probarlo todo y no deja
# llenar la base de datos en el día que pasa entre reinicio y reinicio.
DEMO_PLAN: dict[Resource, int] = {
    Resource.EMPLOYEES_WITH_ACCESS: 5,
    Resource.EMPLOYEES: 10,
    Resource.CLIENTS: 200,
    Resource.VEHICLES: 300,
    Resource.ORDERS_PER_MONTH: 100,
}

# El tope de lo que el superadministrador puede poner: más es un error al
# escribirlo, no un taller grande.
MAX_LIMIT = 1_000_000

# El 409 de cada uno. El de acceso ya existía (F1) y se conserva.
LIMIT_REACHED: dict[Resource, str] = {
    Resource.EMPLOYEES_WITH_ACCESS: "employee_limit_reached",
    Resource.EMPLOYEES: "employee_record_limit_reached",
    Resource.CLIENTS: "client_limit_reached",
    Resource.VEHICLES: "vehicle_limit_reached",
    Resource.ORDERS_PER_MONTH: "order_limit_reached",
}


def has_room(used: int, limit: int) -> bool:
    """Si cabe uno más."""
    return used < limit
