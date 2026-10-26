from pydantic import BaseModel, Field, SecretStr


class InvitationRead(BaseModel):
    workshop_name: str
    employee_name: str
    email: str


class InvitationAccept(BaseModel):
    # SecretStr: si la validación falla, Pydantic incluye la entrada original en
    # el error; con SecretStr sale como '**********' y no en claro (trampa de
    # Applications Tracker). Sin max_length en la contraseña por la misma razón.
    password: SecretStr = Field(min_length=10)


class SuperadminInvitationRead(BaseModel):
    email: str
