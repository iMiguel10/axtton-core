import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmButton } from "@/shared/components/ConfirmButton";
import { Field } from "@/shared/components/form/Field";
import { notify } from "@/shared/components/Toaster";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/shared/components/ui/dialog";
import { Label } from "@/shared/components/ui/label";
import { useDates } from "@/shared/lib/dates";
import { errorMessage } from "@/shared/lib/errors";

import { clientName } from "../clients/clientName";
import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { ordersApi, type OrderDetail, type SignInput } from "./api";
import { ReceptionSummary } from "./ReceptionSummary";
import { SignaturePad, type SignaturePadHandle } from "./SignaturePad";

/**
 * La hoja de recepción (RF-51, RF-52): si está firmada, cómo y cuándo; si no,
 * firmarla en la pantalla del taller o marcarla firmada en papel. Lo que se
 * firma es la orden tal como se ve ahora (su versión): si alguien la cambia
 * mientras tanto, la firma no se guarda.
 */
export function ReceptionSheetCard({
  order,
  onChanged,
}: {
  order: OrderDetail;
  onChanged: () => Promise<unknown>;
}) {
  const { t } = useTranslation();
  const dates = useDates();
  const { workshopId } = useActiveWorkshop();
  const api = ordersApi(workshopId);
  const [signing, setSigning] = useState(false);
  // Una firma no se deja en pausa sin conexión: saldría más tarde, con el
  // cliente ya fuera (como la decisión del portal).
  const sign = useMutation({
    mutationFn: (input: SignInput) => api.signReception(order, input),
    networkMode: "always",
    onSuccess: () => {
      setSigning(false);
      notify(t("reception.signed"));
    },
    onSettled: onChanged,
  });
  const sheet = order.reception_sheet;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("reception.title")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        {sheet ? (
          <>
            <p>
              {sheet.signature_method === "screen"
                ? t("reception.signedOnScreen", {
                    signer: sheet.signer_name ?? t("reception.signerErased"),
                    when: dates.dateTime(sheet.signed_at),
                    by: sheet.recorded_by,
                  })
                : t("reception.signedOnPaper", {
                    when: dates.dateTime(sheet.signed_at),
                    by: sheet.recorded_by,
                  })}
            </p>
            {sheet.quote_waived && <p className="text-sm">{t("reception.waivedSigned")}</p>}
            <p className="text-muted-foreground text-xs">{t("reception.frozenHint")}</p>
          </>
        ) : (
          <>
            <p className="text-muted-foreground text-sm">{t("reception.unsigned")}</p>
            {sign.isError && !signing && (
              <p role="alert" className="text-destructive text-sm">
                {errorMessage(t, sign.error)}
              </p>
            )}
            {order.can_sign_reception && (
              <div className="flex flex-wrap gap-2">
                <Button
                  onClick={() => {
                    sign.reset();
                    setSigning(true);
                  }}
                >
                  {t("reception.signOnScreen")}
                </Button>
                <ConfirmButton
                  variant="outline"
                  title={t("reception.paperTitle")}
                  description={t("reception.paperDescription")}
                  confirmLabel={t("reception.paperConfirm")}
                  disabled={sign.isPending}
                  onConfirm={() => sign.mutate({ method: "paper" })}
                >
                  {t("reception.markPaper")}
                </ConfirmButton>
              </div>
            )}
          </>
        )}
      </CardContent>
      {signing && (
        <SignatureDialog
          order={order}
          pending={sign.isPending}
          error={sign.isError ? errorMessage(t, sign.error) : null}
          onClose={() => setSigning(false)}
          onSign={(input) => sign.mutate(input)}
        />
      )}
    </Card>
  );
}

/** La pantalla que se da al cliente: lo que firma, su nombre y el lienzo. */
function SignatureDialog({
  order,
  pending,
  error,
  onClose,
  onSign,
}: {
  order: OrderDetail;
  pending: boolean;
  error: string | null;
  onClose: () => void;
  onSign: (input: SignInput) => void;
}) {
  const { t } = useTranslation();
  const pad = useRef<SignaturePadHandle>(null);
  const [empty, setEmpty] = useState(true);
  // Quien trae el coche suele ser quien firma; si no, el titular.
  const [signer, setSigner] = useState(
    order.dropped_off_by_name ?? (order.client.name ? clientName(t, order.client.name) : ""),
  );

  // Si la orden cambia mientras firma (otra versión), lo firmado ya no es lo
  // que tiene delante: se borra y vuelve a firmar sobre lo nuevo.
  useEffect(() => {
    pad.current?.clear();
  }, [order.version]);

  const submit = () => {
    const signature = pad.current?.read();
    if (!signature || !signer.trim()) return;
    onSign({ method: "screen", signer_name: signer.trim(), signature });
  };

  return (
    <Dialog open onOpenChange={(open) => !open && !pending && onClose()}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t("reception.screenTitle", { code: order.code })}</DialogTitle>
          <DialogDescription>{t("reception.screenDescription")}</DialogDescription>
        </DialogHeader>
        <ReceptionSummary order={order} forClient />
        {order.quote_waived && (
          <p className="rounded-md border p-3 font-medium">{t("reception.waiverText")}</p>
        )}
        <Field
          id="signer-name"
          label={t("reception.signerName")}
          autoComplete="off"
          value={signer}
          onChange={(event) => setSigner(event.target.value)}
        />
        <div className="grid gap-1.5">
          <div className="flex items-center justify-between">
            <Label>{t("reception.signHere")}</Label>
            <Button size="sm" variant="ghost" onClick={() => pad.current?.clear()}>
              {t("reception.clear")}
            </Button>
          </div>
          <SignaturePad ref={pad} label={t("reception.signHere")} onChange={setEmpty} />
          <p className="text-muted-foreground text-xs">{t("reception.signHint")}</p>
        </div>
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" disabled={pending} onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button disabled={pending || empty || !signer.trim()} onClick={submit}>
            {t("reception.sign")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
