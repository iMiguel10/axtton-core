import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import EmailPassword from "supertokens-web-js/recipe/emailpassword";

import { Field } from "@/shared/components/form/Field";
import { Button } from "@/shared/components/ui/button";
import { apiRequest } from "@/shared/lib/apiClient";
import { errorMessage } from "@/shared/lib/errors";

import { AuthLayout } from "./AuthLayout";
import { newPasswordSchema, type NewPasswordForm } from "./passwordSchema";

/** /superadmin-invitations/:token — el enlace del email de RF-110. */
export function SuperadminInvitationPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { token = "" } = useParams();
  const path = `/superadmin-invitations/${token}`;

  const invitation = useQuery({
    queryKey: ["superadmin-invitation", token],
    queryFn: () => apiRequest<{ email: string }>(path),
  });
  const form = useForm<NewPasswordForm>({ resolver: zodResolver(newPasswordSchema) });
  const { errors } = form.formState;

  const accept = useMutation({
    mutationFn: async (values: NewPasswordForm) => {
      await apiRequest<void>(`${path}/accept`, {
        method: "POST",
        body: { password: values.password },
      });
      await EmailPassword.signIn({
        formFields: [
          { id: "email", value: invitation.data?.email ?? "" },
          { id: "password", value: values.password },
        ],
      });
    },
    onSuccess: () => navigate("/admin", { replace: true }),
  });

  if (invitation.isPending) {
    return <AuthLayout title={t("superadminInvitation.title")}>{t("common.loading")}</AuthLayout>;
  }
  if (invitation.isError) {
    return (
      <AuthLayout title={t("superadminInvitation.title")}>
        <p role="alert">{errorMessage(t, invitation.error)}</p>
        <Link to="/login" className="underline">
          {t("auth.backToSignIn")}
        </Link>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title={t("superadminInvitation.title")}>
      <p>{t("superadminInvitation.intro", { email: invitation.data.email })}</p>
      <form
        className="grid gap-4"
        onSubmit={form.handleSubmit((values) => accept.mutate(values))}
        noValidate
      >
        <Field
          id="password"
          type="password"
          autoComplete="new-password"
          label={t("auth.password")}
          error={errors.password && t(errors.password.message ?? "")}
          {...form.register("password")}
        />
        <Field
          id="confirm"
          type="password"
          autoComplete="new-password"
          label={t("auth.confirmPassword")}
          error={errors.confirm && t(errors.confirm.message ?? "")}
          {...form.register("confirm")}
        />
        {accept.isError && (
          <p role="alert" className="text-destructive text-sm">
            {errorMessage(t, accept.error)}
          </p>
        )}
        <Button type="submit" disabled={accept.isPending}>
          {t("invitation.accept")}
        </Button>
      </form>
    </AuthLayout>
  );
}
