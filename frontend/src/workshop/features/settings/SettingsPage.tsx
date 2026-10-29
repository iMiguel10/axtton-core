import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImageOff } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { ConfirmButton } from "@/shared/components/ConfirmButton";
import { DetailSkeleton } from "@/shared/components/Loading";
import { notify } from "@/shared/components/Toaster";
import { Field } from "@/shared/components/form/Field";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { Label } from "@/shared/components/ui/label";
import { Switch } from "@/shared/components/ui/switch";
import { errorMessage } from "@/shared/lib/errors";
import { bpToInput, parsePercentToBp } from "@/shared/money";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { LaborRatesCard } from "./LaborRatesCard";
import { settingsApi, type WorkshopSettings, type WorkshopSettingsInput } from "./api";

// Los mismos límites que el backend (schemas/settings.py); él vuelve a comprobarlos.
const schema = z.object({
  name: z.string().trim().min(1, "validation.required").max(200),
  legalName: z.string().trim().max(200),
  taxId: z.string().trim().max(20),
  address: z.string().trim().max(300),
  phone: z.string().trim().max(30),
  replyTo: z.union([z.literal(""), z.email("validation.email")]),
  registry: z.string().trim().max(50),
  vat: z.string().refine((value) => parsePercentToBp(value) !== null, "validation.percent"),
  // RF-33: nunca menos de 12 días hábiles.
  validity: z.coerce.number<string>().int("validation.validity").min(12, "validation.validity").max(120, "validation.validity"),
  mechanicsSeePrices: z.boolean(),
});
type Values = z.input<typeof schema>;
type Parsed = z.output<typeof schema>;

function toValues(settings: WorkshopSettings): Values {
  return {
    name: settings.name,
    legalName: settings.legal_name ?? "",
    taxId: settings.tax_id ?? "",
    address: settings.address ?? "",
    phone: settings.phone ?? "",
    replyTo: settings.reply_to_email ?? "",
    registry: settings.industrial_registry_number ?? "",
    vat: bpToInput(settings.default_vat_bp),
    validity: String(settings.quote_validity_business_days),
    mechanicsSeePrices: settings.mechanics_see_sale_prices,
  };
}

function toInput(values: Parsed): WorkshopSettingsInput {
  return {
    name: values.name,
    legal_name: values.legalName || null,
    tax_id: values.taxId || null,
    address: values.address || null,
    phone: values.phone || null,
    reply_to_email: values.replyTo.trim() || null,
    industrial_registry_number: values.registry || null,
    default_vat_bp: parsePercentToBp(values.vat)!,
    quote_validity_business_days: values.validity,
    mechanics_see_sale_prices: values.mechanicsSeePrices,
  };
}

/** Configuración del taller activo (RF-02). Solo llega aquí su administrador. */
export function SettingsPage() {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const api = settingsApi(workshopId);
  const queryClient = useQueryClient();
  const queryKey = ["settings", workshopId];
  const settings = useQuery({ queryKey, queryFn: api.get });
  const save = useMutation({
    mutationFn: (input: WorkshopSettingsInput) => api.update(settings.data!, input),
    onSuccess: () => notify(t("settings.saved")),
    // Tras un 409 también: el formulario vuelve a empezar con lo que guardó el otro.
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey });
      // El nombre sale también en el selector de talleres y en la barra lateral.
      await queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });

  if (!settings.data) {
    return settings.isError ? <p role="alert">{errorMessage(t, settings.error)}</p> : <DetailSkeleton />;
  }
  return (
    <section className="grid gap-6 lg:grid-cols-[3fr_2fr] lg:items-start">
      <Card>
        <CardHeader>
          <CardTitle>{t("settings.legalTitle")}</CardTitle>
          <CardDescription>{t("settings.legalHint")}</CardDescription>
        </CardHeader>
        <CardContent>
          {save.isError && (
            <p role="alert" className="text-destructive mb-4 text-sm">
              {errorMessage(t, save.error)}
            </p>
          )}
          <SettingsForm
            key={settings.data.version}
            settings={settings.data}
            pending={save.isPending}
            onSubmit={(input) => save.mutate(input)}
          />
        </CardContent>
      </Card>
      <div className="grid gap-6">
        <LogoCard hasLogo={settings.data.has_logo} />
        <LaborRatesCard />
      </div>
    </section>
  );
}

function SettingsForm({
  settings,
  pending,
  onSubmit,
}: {
  settings: WorkshopSettings;
  pending: boolean;
  onSubmit: (input: WorkshopSettingsInput) => void;
}) {
  const { t } = useTranslation();
  const form = useForm<Values, unknown, Parsed>({
    resolver: zodResolver(schema),
    defaultValues: toValues(settings),
  });
  const { errors, isDirty } = form.formState;
  const message = (key?: string) => (key ? t(key) : undefined);

  return (
    <form
      className="grid gap-4 md:grid-cols-2"
      onSubmit={form.handleSubmit((values) => onSubmit(toInput(values)))}
      noValidate
    >
      <Field id="settings-name" label={t("settings.name")} error={message(errors.name?.message)} {...form.register("name")} />
      <Field id="settings-legal-name" label={t("settings.legalName")} {...form.register("legalName")} />
      <Field id="settings-tax-id" label={t("settings.taxId")} {...form.register("taxId")} />
      <Field id="settings-registry" label={t("settings.registry")} {...form.register("registry")} />
      <div className="md:col-span-2">
        <Field id="settings-address" label={t("settings.address")} {...form.register("address")} />
      </div>
      <Field id="settings-phone" type="tel" label={t("settings.phone")} {...form.register("phone")} />
      <Field
        id="settings-reply-to"
        type="email"
        label={t("settings.replyTo")}
        error={message(errors.replyTo?.message)}
        {...form.register("replyTo")}
      />
      <h3 className="mt-2 font-medium md:col-span-2">{t("settings.quotesTitle")}</h3>
      <Field
        id="settings-vat"
        inputMode="decimal"
        label={t("settings.defaultVat")}
        error={message(errors.vat?.message)}
        {...form.register("vat")}
      />
      <div className="grid gap-1.5">
        <Field
          id="settings-validity"
          inputMode="numeric"
          label={t("settings.validity")}
          error={message(errors.validity?.message)}
          {...form.register("validity")}
        />
        <p className="text-muted-foreground text-xs">{t("settings.validityHint")}</p>
      </div>
      <div className="flex items-start gap-3 md:col-span-2">
        <Controller
          control={form.control}
          name="mechanicsSeePrices"
          render={({ field }) => (
            <Switch
              id="settings-mechanics-prices"
              checked={field.value}
              onCheckedChange={(checked) => field.onChange(checked)}
            />
          )}
        />
        <div className="grid gap-0.5">
          <Label htmlFor="settings-mechanics-prices">{t("settings.mechanicsSeePrices")}</Label>
          <p className="text-muted-foreground text-xs">{t("settings.mechanicsSeePricesHint")}</p>
        </div>
      </div>
      <p className="text-muted-foreground text-xs md:col-span-2">
        {t("settings.timezone", { timezone: settings.timezone })}
      </p>
      <div className="md:col-span-2">
        <Button type="submit" disabled={pending || !isDirty}>
          {t("common.save")}
        </Button>
      </div>
    </form>
  );
}

const MAX_LOGO_BYTES = 300 * 1024;

/** El logotipo (decisión 0005): el servidor lo vuelve a dibujar y se ve lo que guardó. */
function LogoCard({ hasLogo }: { hasLogo: boolean }) {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const api = settingsApi(workshopId);
  const queryClient = useQueryClient();
  const logo = useQuery({ queryKey: ["logo", workshopId], queryFn: api.logo, enabled: hasLogo });
  const [tooBig, setTooBig] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  // La imagen llega por fetch (lleva la cabecera del taller): se enseña con una
  // URL local, que se suelta al cambiar de imagen o al salir.
  const url = useMemo(() => (logo.data ? URL.createObjectURL(logo.data) : null), [logo.data]);
  useEffect(() => () => {
    if (url) URL.revokeObjectURL(url);
  }, [url]);
  const change = useMutation({
    mutationFn: (file: File | null) => (file ? api.uploadLogo(file) : api.removeLogo()),
    onMutate: () => setTooBig(false),
    onSuccess: (_, file) => notify(t(file ? "settings.logoSaved" : "settings.logoRemoved")),
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["settings", workshopId] });
      await queryClient.invalidateQueries({ queryKey: ["logo", workshopId] });
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.logoTitle")}</CardTitle>
        <CardDescription>{t("settings.logoHint")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="bg-muted/40 flex h-28 items-center justify-center rounded-md border border-dashed p-3">
          {hasLogo && url ? (
            <img src={url} alt={t("settings.logoAlt")} className="max-h-full max-w-full object-contain" />
          ) : (
            <span className="text-muted-foreground flex items-center gap-2 text-sm">
              <ImageOff className="size-4" aria-hidden />
              {t("settings.noLogo")}
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" disabled={change.isPending} onClick={() => picker.current?.click()}>
            {t(hasLogo ? "settings.replaceLogo" : "settings.uploadLogo")}
          </Button>
          <input
            ref={picker}
            type="file"
            accept="image/png,image/jpeg"
            className="sr-only"
            tabIndex={-1}
            aria-hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (!file) return;
              if (file.size > MAX_LOGO_BYTES) {
                setTooBig(true);
                return;
              }
              change.mutate(file);
            }}
          />
          {hasLogo && (
            <ConfirmButton
              variant="ghost"
              size="sm"
              disabled={change.isPending}
              title={t("settings.removeLogo")}
              description={t("settings.confirmRemoveLogo")}
              confirmLabel={t("settings.removeLogo")}
              destructive
              onConfirm={() => change.mutate(null)}
            >
              {t("settings.removeLogo")}
            </ConfirmButton>
          )}
        </div>
        {(tooBig || change.isError) && (
          <p role="alert" className="text-destructive text-sm">
            {tooBig ? t("errors.logo_too_large") : errorMessage(t, change.error)}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
