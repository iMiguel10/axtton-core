import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import EmailPassword from "supertokens-web-js/recipe/emailpassword";
import { z } from "zod";

import { Field } from "@/shared/components/form/Field";
import { Button } from "@/shared/components/ui/button";

import { AuthLayout } from "./AuthLayout";

// Los mensajes son claves de i18n: el esquema no sabe de idiomas.
const schema = z.object({
  email: z.email("validation.email"),
  password: z.string().min(1, "validation.required"),
});
type LoginForm = z.infer<typeof schema>;

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<LoginForm>({ resolver: zodResolver(schema) });
  const { errors, isSubmitting } = form.formState;

  async function onSubmit(values: LoginForm) {
    setError(null);
    const response = await EmailPassword.signIn({
      formFields: [
        { id: "email", value: values.email },
        { id: "password", value: values.password },
      ],
    });
    if (response.status === "OK") {
      navigate("/", { replace: true });
    } else {
      // Mismo mensaje para email desconocido y contraseña incorrecta.
      setError(t("auth.wrongCredentials"));
    }
  }

  return (
    <AuthLayout title={t("auth.signInTitle")}>
      <form className="grid gap-4" onSubmit={form.handleSubmit(onSubmit)} noValidate>
        <Field
          id="email"
          type="email"
          autoComplete="email"
          label={t("auth.email")}
          error={errors.email && t(errors.email.message ?? "")}
          {...form.register("email")}
        />
        <Field
          id="password"
          type="password"
          autoComplete="current-password"
          label={t("auth.password")}
          error={errors.password && t(errors.password.message ?? "")}
          {...form.register("password")}
        />
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <Button type="submit" disabled={isSubmitting}>
          {t("auth.signIn")}
        </Button>
        <Link to="/forgot-password" className="text-muted-foreground text-sm underline">
          {t("auth.forgotPassword")}
        </Link>
      </form>
    </AuthLayout>
  );
}
