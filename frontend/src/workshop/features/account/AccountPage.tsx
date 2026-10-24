import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { Field } from "@/shared/components/form/Field";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { errorMessage } from "@/shared/lib/errors";

import { newPasswordSchema } from "../auth/passwordSchema";
import { accountApi, type AccountPrefix } from "./api";

const changeSchema = z
  .object({ current: z.string().min(1, "validation.required") })
  .and(newPasswordSchema);
type ChangeForm = z.infer<typeof changeSchema>;

/** Mi cuenta: cambiar la contraseña (RF-122) y cerrar las otras sesiones (RF-123). */
export function AccountPage({ prefix }: { prefix: AccountPrefix }) {
  const { t } = useTranslation();
  const api = accountApi(prefix);
  return (
    <section className="grid max-w-xl gap-6">
      <h1 className="text-2xl font-semibold">{t("account.title")}</h1>
      <ChangePassword api={api} />
      <Sessions api={api} prefix={prefix} />
    </section>
  );
}

type Api = ReturnType<typeof accountApi>;

function ChangePassword({ api }: { api: Api }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const form = useForm<ChangeForm>({ resolver: zodResolver(changeSchema) });
  const { errors } = form.formState;
  const change = useMutation({
    mutationFn: (values: ChangeForm) => api.changePassword(values.current, values.password),
    onSuccess: () => {
      form.reset();
      // El backend cerró las demás sesiones: la lista ha cambiado.
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("account.changePassword")}</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-4"
          onSubmit={form.handleSubmit((values) => change.mutate(values))}
          noValidate
        >
          <Field
            id="current"
            type="password"
            autoComplete="current-password"
            label={t("account.currentPassword")}
            error={errors.current && t(errors.current.message ?? "")}
            {...form.register("current")}
          />
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
          {change.isError && (
            <p role="alert" className="text-destructive text-sm">
              {errorMessage(t, change.error)}
            </p>
          )}
          {change.isSuccess && <p role="status">{t("account.passwordChanged")}</p>}
          <Button type="submit" disabled={change.isPending} className="justify-self-start">
            {t("auth.savePassword")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function Sessions({ api, prefix }: { api: Api; prefix: AccountPrefix }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const sessions = useQuery({ queryKey: ["sessions", prefix], queryFn: api.sessions });
  const revoke = useMutation({
    mutationFn: api.revokeOthers,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sessions"] }),
  });
  const format = new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "medium",
    timeStyle: "short",
  });
  const others = sessions.data?.filter((s) => !s.current).length ?? 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("account.sessions")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4">
        {sessions.isPending ? (
          <p>{t("common.loading")}</p>
        ) : sessions.isError ? (
          <p role="alert">{errorMessage(t, sessions.error)}</p>
        ) : (
          <ul className="grid gap-1 text-sm">
            {sessions.data.map((s) => (
              <li key={s.created_at}>
                {t("account.sessionSince", { date: format.format(new Date(s.created_at)) })}
                {s.current && <strong> · {t("account.thisSession")}</strong>}
              </li>
            ))}
          </ul>
        )}
        <Button
          variant="outline"
          className="justify-self-start"
          disabled={others === 0 || revoke.isPending}
          onClick={() => revoke.mutate()}
        >
          {t("account.revokeOthers")}
        </Button>
      </CardContent>
    </Card>
  );
}
