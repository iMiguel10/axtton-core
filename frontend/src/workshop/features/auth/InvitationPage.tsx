import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import EmailPassword from "supertokens-web-js/recipe/emailpassword";

import { LinesSkeleton } from "@/shared/components/Loading";
import { Field } from "@/shared/components/form/Field";
import { Button } from "@/shared/components/ui/button";
import { apiRequest } from "@/shared/lib/apiClient";
import { errorMessage } from "@/shared/lib/errors";

import { AuthLayout } from "./AuthLayout";
import { newPasswordSchema, type NewPasswordForm } from "./passwordSchema";

type Invitation = { workshop_name: string; employee_name: string; email: string };

/**
 * /invitations/:workshopId/:token — la página del enlace del email (RF-04).
 * Si el email ya tiene cuenta (trabaja en otro taller), la contraseña que se
 * escribe es la SUYA: así demuestra que la cuenta es suya (RF-07).
 */
export function InvitationPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { workshopId = "", token = "" } = useParams();
  const path = `/invitations/${workshopId}/${token}`;

  const invitation = useQuery({
    queryKey: ["invitation", workshopId, token],
    queryFn: () => apiRequest<Invitation>(path),
  });
  const form = useForm<NewPasswordForm>({ resolver: zodResolver(newPasswordSchema) });
  const { errors } = form.formState;

  const accept = useMutation({
    mutationFn: async (values: NewPasswordForm) => {
      await apiRequest<void>(`${path}/accept`, {
        method: "POST",
        body: { password: values.password },
      });
      // Con la cuenta ya ligada, se inicia sesión con la misma contraseña.
      await EmailPassword.signIn({
        formFields: [
          { id: "email", value: invitation.data?.email ?? "" },
          { id: "password", value: values.password },
        ],
      });
    },
    onSuccess: () => navigate("/", { replace: true }),
  });

  if (invitation.isPending) {
    return <AuthLayout title={t("invitation.title")}><LinesSkeleton /></AuthLayout>;
  }
  if (invitation.isError) {
    return (
      <AuthLayout title={t("invitation.title")}>
        <p role="alert">{errorMessage(t, invitation.error)}</p>
        <Link to="/login" className="underline">
          {t("auth.backToSignIn")}
        </Link>
      </AuthLayout>
    );
  }

  const { workshop_name, employee_name, email } = invitation.data;
  return (
    <AuthLayout
      title={t("invitation.title")}
      description={t("invitation.intro", { name: employee_name, workshop: workshop_name, email })}
      footer={t("invitation.existingAccountHint")}
    >
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
