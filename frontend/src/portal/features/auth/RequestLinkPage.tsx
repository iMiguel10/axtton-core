import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import { z } from "zod";

import { AuthLayout } from "@/shared/components/AuthLayout";
import { Field } from "@/shared/components/form/Field";
import { LinesSkeleton } from "@/shared/components/Loading";
import { Button } from "@/shared/components/ui/button";
import { errorMessage } from "@/shared/lib/errors";

import { rememberWorkshop } from "../../lib/lastWorkshop";
import { fetchEntry, logoUrl, requestLink } from "./api";

const schema = z.object({ email: z.email("validation.email") });
type RequestForm = z.infer<typeof schema>;

/**
 * La entrada al portal de un taller (RF-40, decisión 0006): `/portal/login/{taller}`.
 * El taller la da en su web, en el resguardo o en sus correos, y el enlace que
 * llega solo abre ese taller.
 */
export function RequestLinkPage() {
  const { workshopId = "" } = useParams();
  return <WorkshopEntry workshopId={workshopId} />;
}

/** La página de entrada de un taller ya conocido, por su id o por su nombre corto. */
export function WorkshopEntry({ workshopId }: { workshopId: string }) {
  const { t } = useTranslation();
  const entry = useQuery({
    queryKey: ["portal", "entry", workshopId],
    queryFn: () => fetchEntry(workshopId),
  });

  useEffect(() => {
    if (entry.isSuccess) rememberWorkshop(workshopId);
  }, [entry.isSuccess, workshopId]);

  if (entry.isError) return <UnknownEntry />;

  return (
    <AuthLayout
      logo={
        entry.data?.has_logo && (
          <img
            src={logoUrl(workshopId)}
            alt={t("portal.login.logoAlt", { workshop: entry.data.workshop_name })}
            className="max-h-16 max-w-48 object-contain"
          />
        )
      }
      title={
        entry.data
          ? t("portal.login.title", { workshop: entry.data.workshop_name })
          : t("portal.login.titleLoading")
      }
      description={t("portal.login.description")}
      tagline={t("portal.tagline")}
    >
      {entry.isPending ? <LinesSkeleton /> : <RequestForm workshopId={workshopId} />}
    </AuthLayout>
  );
}

/** Ni un taller ni un nombre corto que exista: lo mismo en los dos casos. */
export function UnknownEntry() {
  const { t } = useTranslation();
  return (
    <AuthLayout title={t("portal.login.unknownTitle")} tagline={t("portal.tagline")}>
      <p role="alert" className="text-muted-foreground text-center text-sm">
        {t("portal.login.unknownDescription")}
      </p>
    </AuthLayout>
  );
}

function RequestForm({ workshopId }: { workshopId: string }) {
  const { t } = useTranslation();
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<RequestForm>({ resolver: zodResolver(schema) });
  const { errors, isSubmitting } = form.formState;

  async function onSubmit(values: RequestForm) {
    setError(null);
    try {
      await requestLink(workshopId, values.email);
    } catch (failure) {
      // Solo el límite de peticiones o la red: la respuesta normal no dice nada.
      setError(errorMessage(t, failure));
      return;
    }
    // Siempre el mismo mensaje, exista o no el cliente (RF-41).
    setSent(true);
  }

  if (sent) {
    return (
      <div className="grid gap-4">
        <p role="status">{t("portal.login.sent")}</p>
        <Button variant="outline" onClick={() => setSent(false)}>
          {t("portal.login.sendAnother")}
        </Button>
      </div>
    );
  }

  return (
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
        {t("portal.login.submit")}
      </Button>
    </form>
  );
}
