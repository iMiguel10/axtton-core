import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { Field } from "@/shared/components/form/Field";
import { Select } from "@/shared/components/form/Select";
import { Textarea } from "@/shared/components/form/Textarea";
import { Button } from "@/shared/components/ui/button";
import { Label } from "@/shared/components/ui/label";

import type { Client, ClientInput } from "./api";

const KINDS = ["individual", "company"] as const;
const LANGUAGES = ["es", "en"] as const;

// Los mismos límites que el backend (schemas/clients.py); él vuelve a comprobarlos.
const schema = z.object({
  kind: z.enum(KINDS),
  name: z.string().trim().min(1, "validation.required").max(200),
  taxId: z.string().trim().max(20),
  phone: z.string().trim().min(1, "validation.required").max(30),
  email: z.union([z.literal(""), z.email("validation.email")]),
  address: z.string().trim().max(300),
  notes: z.string().trim().max(2000),
  language: z.enum(LANGUAGES),
});
type Values = z.infer<typeof schema>;

function toValues(client?: Client, prefill?: ClientPrefill): Values {
  return {
    kind: client?.kind ?? "individual",
    name: client?.name ?? prefill?.name ?? "",
    taxId: client?.tax_id ?? "",
    phone: client?.phone ?? prefill?.phone ?? "",
    email: client?.email ?? "",
    address: client?.address ?? "",
    notes: client?.notes ?? "",
    language: client?.language ?? "es",
  };
}

function toInput(values: Values): ClientInput {
  return {
    kind: values.kind,
    name: values.name,
    tax_id: values.taxId || null,
    phone: values.phone,
    email: values.email.trim() || null,
    address: values.address || null,
    notes: values.notes || null,
    language: values.language,
  };
}

/**
 * Alta y edición de un cliente (RF-10). Al editar, quien lo usa le pone
 * `key={client.version}`: si otra persona guardó antes (409), la ficha se recarga
 * y el formulario vuelve a empezar con lo último, en vez de pisarlo.
 */
/** Lo que ya se escribió en la búsqueda del mostrador y no encontró a nadie. */
export type ClientPrefill = { name?: string; phone?: string };

export function ClientForm({
  client,
  prefill,
  submitLabel,
  pending,
  onSubmit,
}: {
  client?: Client;
  prefill?: ClientPrefill;
  submitLabel: string;
  pending: boolean;
  onSubmit: (input: ClientInput) => void;
}) {
  const { t } = useTranslation();
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: toValues(client, prefill) });
  const { errors, isDirty } = form.formState;
  const message = (key?: string) => (key ? t(key) : undefined);

  return (
    <form
      className="grid gap-4 md:grid-cols-2"
      onSubmit={form.handleSubmit((values) => onSubmit(toInput(values)))}
      noValidate
    >
      <div className="grid gap-1.5">
        <Label htmlFor="client-kind">{t("clients.kind")}</Label>
        <Select id="client-kind" {...form.register("kind")}>
          {KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {t(`clients.kinds.${kind}`)}
            </option>
          ))}
        </Select>
      </div>
      <Field
        id="client-name"
        label={t("clients.name")}
        autoComplete="off"
        error={message(errors.name?.message)}
        {...form.register("name")}
      />
      <Field
        id="client-phone"
        type="tel"
        label={t("clients.phone")}
        autoComplete="off"
        error={message(errors.phone?.message)}
        {...form.register("phone")}
      />
      <Field
        id="client-email"
        type="email"
        label={t("clients.emailOptional")}
        autoComplete="off"
        error={message(errors.email?.message)}
        {...form.register("email")}
      />
      <Field
        id="client-tax-id"
        label={t("clients.taxIdOptional")}
        autoComplete="off"
        error={message(errors.taxId?.message)}
        {...form.register("taxId")}
      />
      <div className="grid gap-1.5">
        <Label htmlFor="client-language">{t("clients.language")}</Label>
        <Select id="client-language" {...form.register("language")}>
          {LANGUAGES.map((language) => (
            <option key={language} value={language}>
              {t(`clients.languages.${language}`)}
            </option>
          ))}
        </Select>
      </div>
      <div className="md:col-span-2">
        <Field
          id="client-address"
          label={t("clients.address")}
          autoComplete="off"
          {...form.register("address")}
        />
      </div>
      <div className="grid gap-1.5 md:col-span-2">
        <Label htmlFor="client-notes">{t("clients.notes")}</Label>
        <Textarea id="client-notes" {...form.register("notes")} />
        <p className="text-muted-foreground text-xs">{t("clients.notesHint")}</p>
      </div>
      <div className="md:col-span-2">
        <Button type="submit" disabled={pending || (client !== undefined && !isDirty)}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
