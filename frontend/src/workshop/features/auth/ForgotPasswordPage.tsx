import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import EmailPassword from "supertokens-web-js/recipe/emailpassword";
import { z } from "zod";

import { Field } from "@/shared/components/form/Field";
import { Button } from "@/shared/components/ui/button";
import { errorMessage } from "@/shared/lib/errors";

import { AuthLayout } from "./AuthLayout";

const schema = z.object({ email: z.email("validation.email") });
type ForgotForm = z.infer<typeof schema>;

export function ForgotPasswordPage() {
  const { t } = useTranslation();
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<ForgotForm>({ resolver: zodResolver(schema) });
  const { errors, isSubmitting } = form.formState;

  async function onSubmit(values: ForgotForm) {
    setError(null);
    try {
      await EmailPassword.sendPasswordResetEmail({
        formFields: [{ id: "email", value: values.email }],
      });
    } catch (failure) {
      setError(errorMessage(t, failure));
      return;
    }
    // Siempre el mismo mensaje, exista o no la cuenta (RF-121).
    setSent(true);
  }

  return (
    <AuthLayout title={t("auth.forgotTitle")}>
      {sent ? (
        <p role="status">{t("auth.resetEmailSent")}</p>
      ) : (
        <form className="grid gap-4" onSubmit={form.handleSubmit(onSubmit)} noValidate>
          <Field
            id="email"
            type="email"
            autoComplete="email"
            label={t("auth.email")}
            error={errors.email && t(errors.email.message ?? "")}
            {...form.register("email")}
          />
          {error && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}
          <Button type="submit" disabled={isSubmitting}>
            {t("auth.sendResetLink")}
          </Button>
        </form>
      )}
      <Link to="/login" className="text-muted-foreground text-sm underline">
        {t("auth.backToSignIn")}
      </Link>
    </AuthLayout>
  );
}
