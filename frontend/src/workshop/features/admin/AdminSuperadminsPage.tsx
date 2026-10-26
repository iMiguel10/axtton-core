import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { Field } from "@/shared/components/form/Field";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { errorMessage } from "@/shared/lib/errors";

import { superadminsApi } from "./api";

const queryKey = ["admin", "superadmins"];

const schema = z.object({ email: z.email("validation.email") });
type InviteForm = z.infer<typeof schema>;

/** Superadministradores de la instalación e invitar a otro (RF-110). */
export function AdminSuperadminsPage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey, queryFn: superadminsApi.list });
  const form = useForm<InviteForm>({
    resolver: zodResolver(schema),
    defaultValues: { email: "" },
  });
  const { errors } = form.formState;
  const invite = useMutation({
    mutationFn: (values: InviteForm) => superadminsApi.invite(values.email),
    onSuccess: () => {
      form.reset();
      void queryClient.invalidateQueries({ queryKey });
    },
  });
  const date = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" });

  return (
    <section className="grid max-w-2xl gap-6">
      <h1 className="text-2xl font-semibold">{t("superadmins.title")}</h1>
      <Card>
        <CardHeader>
          <CardTitle>{t("superadmins.invite")}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3">
          <p className="text-muted-foreground text-sm">{t("superadmins.inviteHint")}</p>
          <form
            className="grid gap-4 md:grid-cols-[1fr_auto] md:items-end"
            onSubmit={form.handleSubmit((values) => invite.mutate(values))}
            noValidate
          >
            <Field
              id="superadmin-email"
              type="email"
              label={t("auth.email")}
              error={errors.email && t(errors.email.message ?? "")}
              {...form.register("email")}
            />
            <Button type="submit" disabled={invite.isPending}>
              {t("superadmins.send")}
            </Button>
          </form>
          {invite.isError && (
            <p role="alert" className="text-destructive text-sm">
              {errorMessage(t, invite.error)}
            </p>
          )}
          {invite.isSuccess && (
            <p role="status" className="text-sm">
              {t(invite.data.invitation_email_sent ? "superadmins.sent" : "superadmins.sentNoEmail")}
            </p>
          )}
        </CardContent>
      </Card>

      {list.isPending ? (
        <p>{t("common.loading")}</p>
      ) : list.isError ? (
        <p role="alert">{errorMessage(t, list.error)}</p>
      ) : (
        <>
          <div className="grid gap-2">
            <h2 className="text-lg font-medium">{t("superadmins.current")}</h2>
            <ul className="grid gap-1 text-sm">
              {list.data.superadmins.map((s) => (
                <li key={s.email}>
                  {s.email}{" "}
                  <span className="text-muted-foreground">
                    · {t("superadmins.since", { date: date.format(new Date(s.created_at)) })}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          {list.data.pending_invitations.length > 0 && (
            <div className="grid gap-2">
              <h2 className="text-lg font-medium">{t("superadmins.pending")}</h2>
              <ul className="grid gap-1 text-sm">
                {list.data.pending_invitations.map((p) => (
                  <li key={p.id}>
                    {p.email}{" "}
                    <span className="text-muted-foreground">
                      · {t("superadmins.expires", { date: date.format(new Date(p.expires_at)) })}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}
