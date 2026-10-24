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


ROLE_PERMISSIONS: dict[Role, frozenset[Action]] = {
    Role.ADMIN: frozenset(Action),
    Role.MECHANIC: frozenset(),
}


def can(role: str, action: Action) -> bool:
    return action in ROLE_PERMISSIONS.get(Role(role), frozenset())
