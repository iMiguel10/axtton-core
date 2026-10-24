import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import EmailPassword from "supertokens-web-js/recipe/emailpassword";

import { Field } from "@/shared/components/form/Field";
import { Button } from "@/shared/components/ui/button";

import { AuthLayout } from "./AuthLayout";
import { newPasswordSchema, type NewPasswordForm } from "./passwordSchema";

export function ResetPasswordPage() {
  const { t } = useTranslation();
  const [result, setResult] = useState<"done" | "invalid" | "weak" | null>(null);
  const form = useForm<NewPasswordForm>({ resolver: zodResolver(newPasswordSchema) });
  const { errors, isSubmitting } = form.formState;

  async function onSubmit(values: NewPasswordForm) {
    // El SDK lee el token del enlace (?token=...) de la propia URL.
    const response = await EmailPassword.submitNewPassword({
      formFields: [{ id: "password", value: values.password }],
    });
    if (response.status === "OK") setResult("done");
    else if (response.status === "RESET_PASSWORD_INVALID_TOKEN_ERROR") setResult("invalid");
    else setResult("weak");
  }

  if (result === "done") {
    return (
      <AuthLayout title={t("auth.resetTitle")}>
        <p role="status">{t("auth.passwordChanged")}</p>
        <Link to="/login" className="underline">
          {t("auth.signIn")}
        </Link>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title={t("auth.resetTitle")}>
      <form className="grid gap-4" onSubmit={form.handleSubmit(onSubmit)} noValidate>
        <Field
          id="password"
          type="password"
          autoComplete="new-password"
          label={t("auth.newPassword")}
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
        {result && (
          <p role="alert" className="text-destructive text-sm">
            {t(result === "invalid" ? "auth.resetLinkInvalid" : "errors.weak_password")}
          </p>
        )}
        <Button type="submit" disabled={isSubmitting}>
          {t("auth.savePassword")}
        </Button>
      </form>
    </AuthLayout>
  );
}
