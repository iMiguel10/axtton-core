import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { notify } from "@/shared/components/Toaster";
import { Field } from "@/shared/components/form/Field";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { errorMessage } from "@/shared/lib/errors";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { settingsApi, type WorkshopSettings } from "./api";

/**
 * La dirección del portal del cliente (decisión 0007): la que el taller pone en su
 * web o en el resguardo. Con un nombre corto, `/portal/{nombre}`; sin él, o si lo
 * cambia, la del id sigue valiendo siempre.
 */
export function PortalAddressCard({ settings }: { settings: WorkshopSettings }) {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const api = settingsApi(workshopId);
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: (slug: string) => api.update(settings, { portal_slug: slug.trim() || null }),
    onSuccess: () => notify(t("settings.portalSaved")),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["settings", workshopId] }),
  });
  const origin = window.location.origin;
  const byId = `${origin}/portal/login/${workshopId}`;
  const bySlug = settings.portal_slug ? `${origin}/portal/${settings.portal_slug}` : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.portalTitle")}</CardTitle>
        <CardDescription>{t("settings.portalHint")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-2">
          {bySlug && <Address label={t("settings.portalAddress")} url={bySlug} />}
          <Address label={t(bySlug ? "settings.portalAddressById" : "settings.portalAddress")} url={byId} />
        </div>
        {/* Se remonta al cambiar lo guardado; el error vive aquí y no se pierde. */}
        <SlugForm
          key={settings.portal_slug ?? ""}
          initial={settings.portal_slug ?? ""}
          pending={save.isPending}
          onSubmit={(slug) => save.mutate(slug)}
        />
        {save.isError && (
          <p role="alert" className="text-destructive text-sm">
            {errorMessage(t, save.error)}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function SlugForm({
  initial,
  pending,
  onSubmit,
}: {
  initial: string;
  pending: boolean;
  onSubmit: (slug: string) => void;
}) {
  const { t } = useTranslation();
  const [slug, setSlug] = useState(initial);
  return (
    <form
      className="grid gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(slug);
      }}
    >
      <Field
        id="portal-slug"
        label={t("settings.portalSlug")}
        autoComplete="off"
        spellCheck={false}
        maxLength={40}
        value={slug}
        onChange={(event) => setSlug(event.target.value)}
      />
      <p className="text-muted-foreground text-xs">{t("settings.portalSlugHint")}</p>
      <Button type="submit" size="sm" className="justify-self-start" disabled={pending || slug.trim() === initial}>
        {t("common.save")}
      </Button>
    </form>
  );
}

function Address({ label, url }: { label: string; url: string }) {
  const { t } = useTranslation();
  return (
    <div className="grid gap-1">
      <span className="text-muted-foreground text-xs">{label}</span>
      <div className="flex items-center gap-2">
        <code className="bg-muted min-w-0 flex-1 truncate rounded px-2 py-1 text-xs">{url}</code>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={t("settings.copyAddress")}
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(url);
              notify(t("settings.addressCopied"));
            } catch {
              // Sin permiso para el portapapeles: la dirección sigue a la vista.
            }
          }}
        >
          <Copy aria-hidden />
        </Button>
      </div>
    </div>
  );
}
