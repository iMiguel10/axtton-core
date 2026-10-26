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
    # Órdenes: el mecánico las ve todas (en un taller pequeño todos tocan todos
    # los coches, especificación §3); abrirlas, editar la recepción y asignar
    # el responsable es del administrador.
    VIEW_ORDERS = "view_orders"
    MANAGE_ORDERS = "manage_orders"
    # Pasar a reparación, esperando piezas y lista (desde reparación): lo único
    # que el mecánico mueve (especificación §3 y §6).
    MOVE_REPAIR_STATUS = "move_repair_status"
    # Deshacer el último cambio de estado manual: solo el administrador.
    UNDO_STATUS_CHANGE = "undo_status_change"
    # Marcar una orden "sin presupuesto" (RF-27): solo el administrador.
    MARK_NO_QUOTE = "mark_no_quote"
    # Escribir el diagnóstico, las notas internas y registrar trabajos
    # (RF-22, RF-23): los dos roles. Anular un trabajo que anotó otro es de
    # quien gestiona órdenes (MANAGE_ORDERS).
    WRITE_WORKLOG = "write_worklog"


ROLE_PERMISSIONS: dict[Role, frozenset[Action]] = {
    Role.ADMIN: frozenset(Action),
    Role.MECHANIC: frozenset(
        {
            Action.VIEW_CLIENTS,
            Action.VIEW_ORDERS,
            Action.MOVE_REPAIR_STATUS,
            Action.WRITE_WORKLOG,
        }
    ),
}


def can(role: str, action: Action) -> bool:
    return action in ROLE_PERMISSIONS.get(Role(role), frozenset())
