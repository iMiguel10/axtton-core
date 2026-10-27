import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { Wrench } from "lucide-react";
import { useTranslation } from "react-i18next";

import { EmptyState } from "@/shared/components/EmptyState";
import { notify } from "@/shared/components/Toaster";
import { ConfirmButton } from "@/shared/components/ConfirmButton";
import { Field } from "@/shared/components/form/Field";
import { Select } from "@/shared/components/form/Select";
import { Textarea } from "@/shared/components/form/Textarea";
import { Badge } from "@/shared/components/ui/badge";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { Label } from "@/shared/components/ui/label";
import { When } from "@/shared/components/When";
import { errorMessage } from "@/shared/lib/errors";
import { useDates } from "@/shared/lib/dates";
import { cn } from "@/shared/lib/utils";

import { newDraftId, unlessAlreadySaved, useDraft } from "../../lib/useDraft";
import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { fetchStaff, worklogApi, type DiagnosisVersion, type Worklog } from "./api";

/**
 * Diagnóstico para el cliente, trabajos realizados y notas internas de una
 * orden (RF-22, RF-23, RF-25). Lo escribe todo el personal; con la orden
 * cerrada, solo las notas (RF-26).
 *
 * Lo que se está escribiendo es un borrador en el dispositivo (RNF-22): no se
 * pierde al quedarse sin conexión, y lo que no se pudo enviar se envía al
 * volver. Las mutaciones corren con `networkMode: "always"`: sin conexión,
 * TanStack Query las dejaría en pausa en vez de fallar, y el borrador no
 * sabría que está pendiente.
 */
export type WorklogParts = {
  diagnosis: ReactNode;
  work: ReactNode;
  notes: ReactNode;
  /** Para las pestañas: cuántos trabajos sin anular y cuántas notas hay. */
  counts: { work: number; notes: number };
};

/**
 * `layout` recibe las tres partes y decide dónde va cada una (la ficha las pone
 * en pestañas). Así se pide el registro una sola vez y hay un solo "cargando".
 */
export function WorklogSection({
  orderId,
  orderCode,
  closed,
  layout,
}: {
  orderId: string;
  orderCode: string;
  closed: boolean;
  layout: (parts: WorklogParts | null) => ReactNode;
}) {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const queryKey = ["worklog", workshopId, orderId];
  const log = useQuery({ queryKey, queryFn: () => worklogApi(workshopId, orderId).get() });
  const queryClient = useQueryClient();
  // Tras escribir, o tras un 409, se vuelve a pedir: el diagnóstico y la orden
  // (un trabajo cambia su actividad) quedan al día.
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey }),
      queryClient.invalidateQueries({ queryKey: ["order", workshopId, orderId] }),
    ]);

  // Con datos ya cargados, un fallo al recargar (sin conexión) no se los lleva:
  // los formularios, con lo que se está escribiendo, siguen ahí.
  if (!log.data) {
    if (log.isError) return <p role="alert">{errorMessage(t, log.error)}</p>;
    return layout(null);
  }
  const scope = { workshopId, orderId, orderCode };
  return layout({
    counts: {
      work: log.data.work_entries.filter((entry) => !entry.voided_at).length,
      notes: log.data.notes.length,
    },
    diagnosis: (
      <DiagnosisCard
        // Sin key por versión: tras un 409, remontar el editor borraría lo que
        // estaba escribiendo quien guardó segundo.
        scope={scope}
        versions={log.data.diagnosis}
        closed={closed}
        onSaved={refresh}
      />
    ),
    work: <WorkCard scope={scope} log={log.data} closed={closed} onChanged={refresh} />,
    notes: <NotesCard scope={scope} log={log.data} onAdded={refresh} />,
  });
}

type OrderScope = { workshopId: string; orderId: string; orderCode: string };

/** Lo que dice cada tarjeta de su borrador. */
function DraftStatus({ pending, restored }: { pending: boolean; restored: boolean }) {
  const { t } = useTranslation();
  if (pending) {
    return (
      <p role="status" className="text-sm font-medium">
        {t("drafts.pending")}
      </p>
    );
  }
  return restored ? (
    <p role="status" className="text-muted-foreground text-xs">
      {t("drafts.restored")}
    </p>
  ) : null;
}

type DiagnosisDraft = { text: string; base: number };

function DiagnosisCard({
  scope,
  versions,
  closed,
  onSaved,
}: {
  scope: OrderScope;
  versions: DiagnosisVersion[];
  closed: boolean;
  onSaved: () => Promise<unknown>;
}) {
  const { t } = useTranslation();
  const dates = useDates();
  const current = versions[0];
  const currentNo = current?.version_no ?? 0;
  const [text, setText] = useState(current?.text ?? "");
  // La versión desde la que se está editando. Si aparece otra más nueva (la
  // guardó otra persona, quizá mientras este borrador esperaba la conexión),
  // se avisa y se decide; nunca se pisa en silencio (RNF-15).
  const [base, setBase] = useState(currentNo);
  const [showVersions, setShowVersions] = useState(false);
  const save = useMutation({
    mutationFn: (input: DiagnosisDraft) =>
      worklogApi(scope.workshopId, scope.orderId).saveDiagnosis(input.base, input.text),
    networkMode: "always",
    onSuccess: ({ version_no }) => {
      setBase(version_no);
      draft.discard();
      notify(t("worklog.diagnosisSaved"));
    },
    onError: (error, input) => draft.failed(input, error),
    onSettled: onSaved,
  });
  const draft = useDraft<DiagnosisDraft>(
    { ...scope, kind: "diagnosis" },
    {
      onRestore: (saved) => {
        setText(saved.text);
        setBase(saved.base);
      },
      resend: (saved) => save.mutate(saved),
    },
  );
  const edit = (next: DiagnosisDraft) => {
    setText(next.text);
    setBase(next.base);
    // Volver a dejarlo como está guardado no es un borrador.
    if (next.base === currentNo && next.text.trim() === (current?.text ?? "").trim()) {
      draft.discard();
    } else {
      draft.save(next);
    }
  };
  const outdated = currentNo !== base;
  const unchanged = !outdated && text.trim() === (current?.text ?? "").trim();

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("worklog.diagnosis")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        <p className="text-muted-foreground text-xs">{t("worklog.diagnosisHint")}</p>
        {outdated && current && !closed ? (
          <div role="alert" className="grid gap-2 rounded-lg border border-amber-500/50 p-3 text-sm">
            <p>
              {t("worklog.diagnosisChanged", { name: current.employee_name })}
            </p>
            <p className="text-muted-foreground whitespace-pre-line">{current.text}</p>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  edit({ text: current.text, base: currentNo });
                  save.reset();
                }}
              >
                {t("worklog.useTheirs")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  edit({ text, base: currentNo });
                  save.reset();
                }}
              >
                {t("worklog.keepMine")}
              </Button>
            </div>
          </div>
        ) : (
          save.isError &&
          !draft.pending && (
            <p role="alert" className="text-destructive text-sm">
              {errorMessage(t, save.error)}
            </p>
          )
        )}
        {closed ? (
          <p className="whitespace-pre-line">{current?.text ?? "—"}</p>
        ) : (
          <form
            className="grid gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              save.mutate({ text, base });
            }}
          >
            <Label htmlFor="diagnosis-text" className="sr-only">
              {t("worklog.diagnosis")}
            </Label>
            <Textarea
              id="diagnosis-text"
              className="min-h-28"
              value={text}
              onChange={(event) => edit({ text: event.target.value, base })}
            />
            <DraftStatus pending={draft.pending} restored={draft.restored} />
            <div>
              <Button type="submit" size="sm" disabled={save.isPending || outdated || unchanged || !text.trim()}>
                {t("worklog.saveDiagnosis")}
              </Button>
            </div>
          </form>
        )}
        {current && (
          <p className="text-muted-foreground text-xs">
            {t("worklog.version", {
              number: current.version_no,
              name: current.employee_name,
              when: dates.dateTime(current.created_at),
            })}
            {versions.length > 1 && (
              <>
                {" · "}
                <button
                  type="button"
                  className="underline"
                  aria-expanded={showVersions}
                  onClick={() => setShowVersions(!showVersions)}
                >
                  {t(showVersions ? "worklog.hideVersions" : "worklog.showVersions", {
                    count: versions.length - 1,
                  })}
                </button>
              </>
            )}
          </p>
        )}
        {showVersions && (
          <ol className="grid gap-2 border-l-2 pl-3">
            {versions.slice(1).map((version) => (
              <li key={version.version_no} className="grid gap-0.5">
                <span className="text-muted-foreground text-xs">
                  {t("worklog.version", {
                    number: version.version_no,
                    name: version.employee_name,
                    when: dates.dateTime(version.created_at),
                  })}
                </span>
                <p className="text-sm whitespace-pre-line">{version.text}</p>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

function today(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

type WorkDraft = { id: string; worker: string; description: string; workedOn: string; hours: string };

function WorkCard({
  scope,
  log,
  closed,
  onChanged,
}: {
  scope: OrderScope;
  log: Worklog;
  closed: boolean;
  onChanged: () => Promise<unknown>;
}) {
  const { t, i18n } = useTranslation();
  const dates = useDates();
  const { employeeId } = useActiveWorkshop();
  const api = worklogApi(scope.workshopId, scope.orderId);
  const staff = useQuery({
    queryKey: ["staff", scope.workshopId],
    queryFn: () => fetchStaff(scope.workshopId),
    staleTime: 60_000,
  });
  const blank = (): WorkDraft => ({
    id: newDraftId(),
    worker: employeeId,
    description: "",
    workedOn: today(),
    hours: "",
  });
  const [form, setForm] = useState(blank);

  const add = useMutation({
    mutationFn: (input: WorkDraft) =>
      unlessAlreadySaved(
        api.addWork({
          id: input.id,
          employee_id: input.worker,
          description: input.description,
          worked_on: input.workedOn,
          // Se admite "1,5" como en el resto de importes en español.
          hours: input.hours.trim() ? input.hours.trim().replace(",", ".") : null,
        }),
      ),
    networkMode: "always",
    onSuccess: () => {
      setForm(blank());
      draft.discard();
    },
    onError: (error, input) => draft.failed(input, error),
    onSettled: onChanged,
  });
  const draft = useDraft<WorkDraft>(
    { ...scope, kind: "work" },
    { onRestore: setForm, resend: (saved) => add.mutate(saved) },
  );
  const edit = (change: Partial<WorkDraft>) => {
    // Lo pendiente quizá llegó (se perdió solo la respuesta): si se cambia, es
    // otro envío con otro id. Con el mismo, el servidor lo tomaría por un
    // reenvío y el cambio se perdería sin avisar.
    const next = { ...form, ...change, id: draft.pending ? newDraftId() : form.id };
    setForm(next);
    // Quién y cuándo vienen ya puestos: sin qué ni horas, no hay nada escrito.
    if (!next.description.trim() && !next.hours.trim()) draft.discard();
    else draft.save(next);
  };
  const voiding = useMutation({
    mutationFn: (entryId: string) => api.voidWork(entryId),
    onSettled: onChanged,
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    add.mutate(form);
  };
  const hoursOf = (value: string | null) =>
    value === null ? "—" : Number(value).toLocaleString(i18n.language);
  const error = voiding.error ?? (draft.pending ? null : add.error);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("worklog.work")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4">
        {log.workers.length > 0 && (
          <p className="text-sm">
            <span className="text-muted-foreground">{t("worklog.workers")}:</span>{" "}
            {log.workers.join(", ")}
          </p>
        )}
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {errorMessage(t, error)}
          </p>
        )}
        {log.work_entries.length === 0 ? (
          <EmptyState compact icon={Wrench} title={t("worklog.noWork")} />
        ) : (
          <ul className="grid gap-2">
            {log.work_entries.map((entry) => (
              <li
                key={entry.id}
                className={cn("grid gap-0.5 rounded-lg border p-2", entry.voided_at && "opacity-60")}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className={cn("font-medium", entry.voided_at && "line-through")}>
                    {entry.description}
                  </span>
                  {entry.voided_at && <Badge variant="secondary">{t("worklog.voided")}</Badge>}
                  {entry.can_void && !closed && (
                    <ConfirmButton
                      variant="ghost"
                      size="xs"
                      className="ml-auto"
                      disabled={voiding.isPending}
                      title={t("worklog.void")}
                      description={t("worklog.confirmVoid")}
                      confirmLabel={t("worklog.void")}
                      destructive
                      onConfirm={() => voiding.mutate(entry.id)}
                    >
                      {t("worklog.void")}
                    </ConfirmButton>
                  )}
                </div>
                <span className="text-muted-foreground text-xs">
                  {t("worklog.entryMeta", {
                    worker: entry.employee.name,
                    date: dates.day(entry.worked_on),
                    hours: hoursOf(entry.hours),
                    recorder: entry.recorded_by_name,
                  })}
                </span>
              </li>
            ))}
          </ul>
        )}
        {!closed && (
          <form className="grid gap-3 border-t pt-3" onSubmit={submit}>
            <div className="grid gap-3 md:grid-cols-[2fr_1fr_1fr_1fr_auto] md:items-end">
              <Field
                id="work-description"
                label={t("worklog.description")}
                required
                value={form.description}
                onChange={(event) => edit({ description: event.target.value })}
              />
              <div className="grid gap-1.5">
                <Label htmlFor="work-worker">{t("worklog.doneBy")}</Label>
                <Select id="work-worker" value={form.worker} onChange={(event) => edit({ worker: event.target.value })}>
                  {(staff.data ?? []).map((member) => (
                    <option key={member.id} value={member.id}>
                      {member.name}
                    </option>
                  ))}
                </Select>
              </div>
              <Field
                id="work-date"
                type="date"
                label={t("worklog.date")}
                required
                value={form.workedOn}
                onChange={(event) => edit({ workedOn: event.target.value })}
              />
              <Field
                id="work-hours"
                inputMode="decimal"
                label={t("worklog.hours")}
                value={form.hours}
                onChange={(event) => edit({ hours: event.target.value })}
              />
              <Button type="submit" disabled={add.isPending || !form.description.trim() || !form.workedOn}>
                {t("worklog.addWork")}
              </Button>
            </div>
            <DraftStatus pending={draft.pending} restored={draft.restored} />
          </form>
        )}
      </CardContent>
    </Card>
  );
}

type NoteDraft = { id: string; body: string };

function NotesCard({
  scope,
  log,
  onAdded,
}: {
  scope: OrderScope;
  log: Worklog;
  onAdded: () => Promise<unknown>;
}) {
  const { t } = useTranslation();
  const [note, setNote] = useState<NoteDraft>(() => ({ id: newDraftId(), body: "" }));
  const add = useMutation({
    mutationFn: (input: NoteDraft) =>
      unlessAlreadySaved(worklogApi(scope.workshopId, scope.orderId).addNote(input.id, input.body)),
    networkMode: "always",
    onSuccess: () => {
      setNote({ id: newDraftId(), body: "" });
      draft.discard();
    },
    onError: (error, input) => draft.failed(input, error),
    onSettled: onAdded,
  });
  const draft = useDraft<NoteDraft>(
    { ...scope, kind: "note" },
    { onRestore: setNote, resend: (saved) => add.mutate(saved) },
  );
  const edit = (body: string) => {
    const next = { id: draft.pending ? newDraftId() : note.id, body };
    setNote(next);
    if (body.trim()) draft.save(next);
    else draft.discard();
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("worklog.notes")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        <p className="text-muted-foreground text-xs">{t("worklog.notesHint")}</p>
        {log.notes.length > 0 && (
          <ol className="grid gap-2">
            {log.notes.map((entry) => (
              <li key={entry.seq} className="grid gap-0.5 border-l-2 pl-3">
                <span className="text-muted-foreground text-xs">
                  {entry.employee_name} · <When iso={entry.created_at} />
                </span>
                <p className="text-sm whitespace-pre-line">{entry.body}</p>
              </li>
            ))}
          </ol>
        )}
        {add.isError && !draft.pending && (
          <p role="alert" className="text-destructive text-sm">
            {errorMessage(t, add.error)}
          </p>
        )}
        <form
          className="grid gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            add.mutate(note);
          }}
        >
          <Label htmlFor="note-body" className="sr-only">
            {t("worklog.newNote")}
          </Label>
          <Textarea
            id="note-body"
            placeholder={t("worklog.newNote")}
            value={note.body}
            onChange={(event) => edit(event.target.value)}
          />
          <DraftStatus pending={draft.pending} restored={draft.restored} />
          <div>
            <Button type="submit" size="sm" disabled={add.isPending || !note.body.trim()}>
              {t("worklog.addNote")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
