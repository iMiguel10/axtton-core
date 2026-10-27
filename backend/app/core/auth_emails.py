"""Emails y efectos de la recuperación de contraseña (RF-121).

Sin esto, SuperTokens enviaría el email de recuperación con su propio servicio,
desde sus servidores: los datos de nuestros usuarios saldrían a un tercero y
el remitente no sería el de la plataforma (RF-68). Aquí se sustituye por
nuestro EmailSender.
"""

from typing import Any

from supertokens_python.ingredients.emaildelivery.types import EmailDeliveryInterface
from supertokens_python.recipe.emailpassword.interfaces import (
    APIInterface,
    APIOptions,
    PasswordResetPostOkResult,
)
from supertokens_python.recipe.emailpassword.types import (
    EmailTemplateVars,
    FormField,
)
from supertokens_python.recipe.session.asyncio import revoke_all_sessions_for_user

from app.domain.emails import password_reset_email
from app.infra.email import compose, current_email_sender


class PlatformPasswordResetEmail(EmailDeliveryInterface[EmailTemplateVars]):
    async def send_email(
        self, template_vars: EmailTemplateVars, user_context: dict[str, Any]
    ) -> None:
        sender = current_email_sender()
        if not sender.enabled:
            # Sin SMTP no hay recuperación por email (RNF-32): no se envía nada,
            # y la respuesta de la API es la misma de siempre.
            return
        link = template_vars.password_reset_link  # type: ignore[union-attr]
        await sender.send(
            compose(template_vars.user.email, password_reset_email(link=link))
        )


def password_reset_effects(original: APIInterface) -> APIInterface:
    """Al completar la recuperación se cierran TODAS las sesiones de la cuenta:
    si alguien había robado una, recuperar la contraseña tiene que echarlo
    (trampa resuelta en Applications Tracker). Un access token ya emitido sigue
    sirviendo hasta caducar (5 minutos); lo que se corta es la renovación.
    """
    original_post = original.password_reset_post

    async def password_reset_post(
        form_fields: list[FormField],
        token: str,
        tenant_id: str,
        api_options: APIOptions,
        user_context: dict[str, Any],
    ) -> Any:
        result = await original_post(
            form_fields, token, tenant_id, api_options, user_context
        )
        if isinstance(result, PasswordResetPostOkResult):
            await revoke_all_sessions_for_user(result.user.id)
        return result

    original.password_reset_post = password_reset_post  # type: ignore[method-assign]
    return original
