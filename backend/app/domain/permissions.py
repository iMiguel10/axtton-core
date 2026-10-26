"""Matriz de permisos por rol en el taller (especificación §3, RNF-03).

Una sola función, `can`, decide qué puede hacer cada rol. Ningún endpoint
compara roles por su cuenta: así, pasar algún día a permisos configurables es
cambiar este mapa, no buscar `if role == ...` repartidos por el código
(especificación §12).
"""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    MECHANIC = "mechanic"


class Action(StrEnum):
    MANAGE_EMPLOYEES = "manage_employees"
    VIEW_COSTS = "view_costs"
    # Consultar el registro de auditoría del taller (RNF-16, especificación §3).
    VIEW_AUDIT_LOG = "view_audit_log"
    # Clientes y vehículos (especificación §3): el mecánico solo los ve. Una
    # sola acción para los dos, como la fila de la matriz.
    VIEW_CLIENTS = "view_clients"
    MANAGE_CLIENTS = "manage_clients"
    # Cambiar el titular de un vehículo (RF-12): fila propia en la matriz.
    CHANGE_VEHICLE_OWNER = "change_vehicle_owner"


ROLE_PERMISSIONS: dict[Role, frozenset[Action]] = {
    Role.ADMIN: frozenset(Action),
    Role.MECHANIC: frozenset({Action.VIEW_CLIENTS}),
}


def can(role: str, action: Action) -> bool:
    return action in ROLE_PERMISSIONS.get(Role(role), frozenset())
