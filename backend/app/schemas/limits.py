from pydantic import BaseModel

from app.domain.limits import Resource


class LimitUsage(BaseModel):
    """Un límite del taller (§10) y lo gastado: lo ve el superadministrador en
    /admin y el administrador del taller en su cuenta."""

    resource: Resource
    used: int
    limit: int
