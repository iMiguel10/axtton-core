"""Qué sale antes: el commit, la respuesta o el email (CLAUDE.md §8).

CLAUDE.md dice: "Un email se envía después del commit, nunca dentro de la
transacción [...] Desde un endpoint del taller se usa BackgroundTasks de FastAPI,
que se ejecuta después de enviar la respuesta y, por tanto, después del commit de
la dependencia del taller." Estas pruebas lo comprueban mirando la base de datos
desde OTRA conexión en el momento exacto en que sale el email o la respuesta: si
la fila todavía no se ve, es que la transacción aún no se había confirmado.

Al cerrar F1 fallaban: con el ámbito por defecto de FastAPI ("request"), la salida
de la dependencia con yield (el commit) llegaba después de la respuesta y de las
BackgroundTasks. Se arregló con Depends(..., scope="function").
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.types import Message, Receive, Scope, Send

from app.api.deps import get_email_sender
from app.core.tokens import hash_token
from app.infra.email import Email
from app.main import app
from app.scripts.reset_data import truncate_all
from tests.conftest import Engines
from tests.test_audit import open_workshop
from tests.test_employees import AdminSession, add_mechanic


@dataclass
class CommitCheckingSender:
    """Doble del correo que, al enviar, mira si la invitación ya está confirmada."""

    engine: AsyncEngine
    enabled: bool = True
    committed_when_sent: list[bool] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)

    async def saved(self, token: str) -> bool:
        async with self.engine.connect() as conn:
            found = await conn.scalar(
                text("SELECT count(*) FROM invitations WHERE token_hash = :h"),
                {"h": hash_token(token)},
            )
        return found == 1

    async def send(self, email: Email) -> None:
        token = email.body.split("/invitations/", 1)[1].split()[0].split("/", 1)[1]
        self.tokens.append(token)
        self.committed_when_sent.append(await self.saved(token))


@pytest_asyncio.fixture
async def admin(client: AsyncClient) -> AdminSession:
    await truncate_all()
    return await open_workshop(client, "Talleres Pérez")


@pytest.mark.asyncio
async def test_the_invitation_email_leaves_only_after_the_invitation_is_saved(
    client: AsyncClient, admin: AdminSession, engines: Engines
) -> None:
    sender = CommitCheckingSender(engines.platform)
    app.dependency_overrides[get_email_sender] = lambda: sender
    try:
        employee_id = await add_mechanic(client, admin)
        response = await client.post(
            f"/api/v1/workshop/employees/{employee_id}/invitation",
            json={"email": "juan@example.com"},
            headers=admin.headers,
        )
    finally:
        app.dependency_overrides.pop(get_email_sender, None)
    assert response.json() == {"invitation_email_queued": True}
    # Prueba de control: el token se extrajo bien y, terminada la petición, la
    # invitación sí está guardada (si no, el False de abajo no probaría nada).
    assert [await sender.saved(t) for t in sender.tokens] == [True]
    assert sender.committed_when_sent == [True]


@pytest.mark.asyncio
async def test_a_successful_answer_is_sent_only_after_the_change_is_committed(
    client: AsyncClient, admin: AdminSession, engines: Engines
) -> None:
    committed_at_response: list[bool] = []

    async def watching(scope: Scope, receive: Receive, send: Send) -> None:
        async def spy(message: Message) -> None:
            if message["type"] == "http.response.start":
                async with engines.platform.connect() as conn:
                    found = await conn.scalar(
                        text("SELECT count(*) FROM employees WHERE name = 'Visible'")
                    )
                committed_at_response.append(found == 1)
            await send(message)

        await app(scope, receive, spy)

    async with AsyncClient(
        transport=ASGITransport(app=watching), base_url="http://test"
    ) as watched:
        response = await watched.post(
            "/api/v1/workshop/employees",
            json={"name": "Visible", "role": "mechanic"},
            headers=admin.headers,
        )
    assert response.status_code == 201
    assert committed_at_response == [True]


@pytest.mark.asyncio
async def test_after_the_answer_the_change_is_visible_to_the_next_request(
    client: AsyncClient, admin: AdminSession
) -> None:
    """Lo que sí se cumple hoy con el transporte en memoria: httpx espera a que la
    aplicación ASGI termine (commit incluido) antes de devolver la respuesta. Con
    un servidor real (uvicorn) la respuesta sale por el socket antes; por eso la
    prueba de arriba mira el momento exacto del envío."""
    await add_mechanic(client, admin, "Inmediato")
    response = await client.get("/api/v1/workshop/employees", headers=admin.headers)
    assert "Inmediato" in [e["name"] for e in response.json()]


@pytest_asyncio.fixture(autouse=True)
async def _no_leftover_overrides() -> AsyncIterator[None]:
    yield
    app.dependency_overrides.pop(get_email_sender, None)
