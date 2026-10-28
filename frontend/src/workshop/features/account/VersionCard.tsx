import { useTranslation } from "react-i18next";

import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { APP_COMMIT, APP_VERSION, useServerMeta, versionLabel } from "@/shared/lib/version";

/** Qué versión es esta: lo primero que hay que decir al avisar de un fallo. */
export function VersionCard() {
  const { t } = useTranslation();
  const meta = useServerMeta();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("version.title")}</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-muted-foreground">{t("version.app")}</dt>
          <dd className="tabular-nums">{versionLabel(APP_VERSION, APP_COMMIT)}</dd>
          <dt className="text-muted-foreground">{t("version.server")}</dt>
          <dd className="tabular-nums">
            {meta.data ? versionLabel(meta.data.version, meta.data.commit) : "—"}
          </dd>
        </dl>
      </CardContent>
    </Card>
  );
}
