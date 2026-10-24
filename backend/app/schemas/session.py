from pydantic import BaseModel

from app.domain.actors import Actor


class WhoAmI(BaseModel):
    actor: Actor
