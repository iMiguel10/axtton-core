"""Inicialización del SDK de SuperTokens (arquitectura A4, §2).

Debe ejecutarse antes de crear la app de FastAPI. El core solo es accesible por
la red interna de Docker.
"""

from typing import Any

from supertokens_python import InputAppInfo, SupertokensConfig, init
from supertokens_python.ingredients.emaildelivery.types import (
    EmailDeliveryConfig,
    EmailDeliveryInterface,
)
from supertokens_python.recipe import emailpassword, passwordless, session
from supertokens_python.recipe.emailpassword import EmailPasswordOverrideConfig
from supertokens_python.recipe.emailpassword.interfaces import APIInterface
from supertokens_python.recipe.passwordless import (
    ContactEmailOnlyConfig,
    PasswordlessOverrideConfig,
)
from supertokens_python.recipe.passwordless.interfaces import (
    APIInterface as PasswordlessAPIInterface,
)
from supertokens_python.recipe.passwordless.types import (
    PasswordlessLoginEmailTemplateVars,
)
from supertokens_python.recipe.session import SessionOverrideConfig
from supertokens_python.types.response import GeneralErrorResponse

from app.core.auth_emails import PlatformPasswordResetEmail, password_reset_effects
from app.core.config import get_settings
from app.core.sessions import emailpassword_override, session_override

# Las rutas de SuperTokens cuelgan de /api, como todo lo de la API: así el proxy
# (Vite en desarrollo, el servidor web en producción) solo tiene que reenviar /api.
AUTH_BASE_PATH = "/api/auth"


def _no_public_signup(original: APIInterface) -> APIInterface:
    """No hay registro abierto (RF-01): el personal entra siempre por invitación
    y el superadministrador se crea con un comando de servidor.

    Se anula la operación, no una URL: SuperTokens atiende el registro en varias
    rutas (/signup, /public/signup...), y bloquear una dejaría las otras abiertas
    (trampa encontrada en Applications Tracker). Las cuentas se crean desde el
    backend con la función de la receta, que no pasa por aquí.
    """

    async def sign_up_post(*_args: Any, **_kwargs: Any) -> GeneralErrorResponse:
        return GeneralErrorResponse("signup_disabled")

    original.sign_up_post = sign_up_post  # type: ignore[method-assign]
    # "¿Existe una cuenta con este email?" solo le sirve al formulario de
    # registro, que no hay. Abierta, cualquiera averiguaría qué emails tienen
    # cuenta y anularía el "responde igual" de la recuperación (RF-121). Se apaga
    # la operación, que SuperTokens atiende en varias rutas (hallazgo del cierre
    # de F1, tests/test_adverse_f1.py).
    original.disable_email_exists_get = True
    return original


def _no_public_passwordless(
    original: PasswordlessAPIInterface,
) -> PasswordlessAPIInterface:
    """Las rutas de la receta passwordless de SuperTokens no existen (decisión 0006).

    El portal entra por las nuestras (`/api/v1/portal/auth/*`), que ligan cada
    enlace a un taller. Las de SuperTokens crearían códigos que no saben de
    talleres, y consumir uno abriría una sesión sin el taller ni el cliente
    (core/sessions.py no la daría por buena, pero mejor que ni exista). Tampoco
    "¿existe este email?": diría quién es cliente (RF-41).
    """
    original.disable_create_code_post = True
    original.disable_resend_code_post = True
    original.disable_consume_code_post = True
    original.disable_email_exists_get = True
    original.disable_phone_number_exists_get = True
    return original


class NoPasswordlessEmail(EmailDeliveryInterface[PasswordlessLoginEmailTemplateVars]):
    """La receta nunca envía correo: no emitimos sus códigos (`signinup` crea el
    usuario sin enviar nada). Si algo llegara a pedirlo, falla aquí en vez de
    salir por el servicio de SuperTokens, desde sus servidores."""

    async def send_email(
        self,
        template_vars: PasswordlessLoginEmailTemplateVars,
        user_context: dict[str, Any],
    ) -> None:
        raise RuntimeError("passwordless emails are never sent")


def init_supertokens() -> None:
    settings = get_settings()
    init(
        app_info=InputAppInfo(
            app_name="AXTTON CORE",
            # Un solo dominio: la API se ve desde el navegador en el mismo origen
            # que la web, así que las cookies de sesión son de primera parte.
            api_domain=settings.app_url,
            website_domain=settings.app_url,
            api_base_path=AUTH_BASE_PATH,
            website_base_path="/",
        ),
        supertokens_config=SupertokensConfig(
            connection_uri=settings.supertokens_connection_uri,
            api_key=settings.supertokens_api_key,
        ),
        framework="fastapi",
        recipe_list=[
            # Cookies httpOnly en el navegador y Bearer fuera de él (decisión 0003
            # de Applications Tracker): es la costura para las apps móviles.
            session.init(override=SessionOverrideConfig(functions=session_override)),
            emailpassword.init(
                # El email de recuperación sale por nuestro SMTP, no por el
                # servicio de SuperTokens (auth_emails.py).
                email_delivery=EmailDeliveryConfig(
                    service=PlatformPasswordResetEmail()
                ),
                override=EmailPasswordOverrideConfig(
                    functions=emailpassword_override,
                    apis=lambda original: password_reset_effects(
                        _no_public_signup(original)
                    ),
                ),
            ),
            # Solo para tener un usuario por email con el que crear la sesión
            # del cliente; los enlaces son nuestros (decisión 0006).
            passwordless.init(
                contact_config=ContactEmailOnlyConfig(),
                flow_type="MAGIC_LINK",
                email_delivery=EmailDeliveryConfig(service=NoPasswordlessEmail()),
                override=PasswordlessOverrideConfig(apis=_no_public_passwordless),
            ),
        ],
        mode="asgi",
        # Sin envío de datos de uso a SuperTokens.
        telemetry=False,
    )
