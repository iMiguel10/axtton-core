import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Field } from "@/shared/components/form/Field";
import { Select } from "@/shared/components/form/Select";
import { Textarea } from "@/shared/components/form/Textarea";
import { Badge } from "@/shared/components/ui/badge";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { Label } from "@/shared/components/ui/label";
import { errorMessage } from "@/shared/lib/errors";
import { cn } from "@/shared/lib/utils";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { fetchStaff, worklogApi, type DiagnosisVersion, type Worklog } from "./api";
import { formatDateTime } from "./OrderBits";

/**
 * Diagnóstico para el cliente, trabajos realizados y notas internas de una
 * orden (RF-22, RF-23, RF-25). Lo escribe todo el personal; con la orden
 * cerrada, solo las notas (RF-26).
 */
export function WorklogSection({ orderId, closed }: { orderId: string; closed: boolean }) {
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

  if (log.isPending) return <p>{t("common.loading")}</p>;
  if (log.isError) return <p role="alert">{errorMessage(t, log.error)}</p>;
  return (
    <>
      <DiagnosisCard
        // Sin key por versión: tras un 409, remontar el editor borraría lo que
        // estaba escribiendo quien guardó segundo.
        orderId={orderId}
        versions={log.data.diagnosis}
        closed={closed}
        onSaved={refresh}
      />
      <WorkCard orderId={orderId} log={log.data} closed={closed} onChanged={refresh} />
      <NotesCard orderId={orderId} log={log.data} onAdded={refresh} />
    </>
  );
}

function DiagnosisCard({
  orderId,
  versions,
  closed,
  onSaved,
}: {
  orderId: string;
  versions: DiagnosisVersion[];
  closed: boolean;
  onSaved: () => Promise<unknown>;
}) {
  const { t, i18n } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const current = versions[0];
  const currentNo = current?.version_no ?? 0;
  const [text, setText] = useState(current?.text ?? "");
  // La versión desde la que se está editando. Si aparece otra más nueva (la
  // guardó otra persona), se avisa y se decide; nunca se pisa en silencio
  // (RNF-15).
  const [base, setBase] = useState(currentNo);
  const [showVersions, setShowVersions] = useState(false);
  const save = useMutation({
    mutationFn: () => worklogApi(workshopId, orderId).saveDiagnosis(base, text),
    onSuccess: ({ version_no }) => setBase(version_no),
    onSettled: onSaved,
  });
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
                  setText(current.text);
                  setBase(currentNo);
                  save.reset();
                }}
              >
                {t("worklog.useTheirs")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setBase(currentNo);
                  save.reset();
                }}
              >
                {t("worklog.keepMine")}
              </Button>
            </div>
          </div>
        ) : (
          save.isError && (
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
              save.mutate();
            }}
          >
            <Label htmlFor="diagnosis-text" className="sr-only">
              {t("worklog.diagnosis")}
            </Label>
            <Textarea
              id="diagnosis-text"
              className="min-h-28"
              value={text}
              onChange={(event) => setText(event.target.value)}
            />
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
              when: formatDateTime(current.created_at, i18n.language),
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
                    when: formatDateTime(version.created_at, i18n.language),
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

function WorkCard({
  orderId,
  log,
  closed,
  onChanged,
}: {
  orderId: string;
  log: Worklog;
  closed: boolean;
  onChanged: () => Promise<unknown>;
}) {
  const { t, i18n } = useTranslation();
  const { workshopId, employeeId } = useActiveWorkshop();
  const api = worklogApi(workshopId, orderId);
  const staff = useQuery({
    queryKey: ["staff", workshopId],
    queryFn: () => fetchStaff(workshopId),
    staleTime: 60_000,
  });
  const [worker, setWorker] = useState(employeeId);
  const [description, setDescription] = useState("");
  const [workedOn, setWorkedOn] = useState(today);
  const [hours, setHours] = useState("");

  const action = useMutation({
    mutationFn: (run: () => Promise<unknown>) => run(),
    onSettled: onChanged,
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    action.mutate(async () => {
      await api.addWork({
        employee_id: worker,
        description,
        worked_on: workedOn,
        // Se admite "1,5" como en el resto de importes en español.
        hours: hours.trim() ? hours.trim().replace(",", ".") : null,
      });
      setDescription("");
      setHours("");
    });
  };
  const hoursOf = (value: string | null) =>
    value === null ? "—" : Number(value).toLocaleString(i18n.language);

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
        {action.isError && (
          <p role="alert" className="text-destructive text-sm">
            {errorMessage(t, action.error)}
          </p>
        )}
        {log.work_entries.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("worklog.noWork")}</p>
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
                    <Button
                      variant="ghost"
                      size="xs"
                      className="ml-auto"
                      disabled={action.isPending}
                      onClick={() => {
                        if (window.confirm(t("worklog.confirmVoid"))) {
                          action.mutate(() => api.voidWork(entry.id));
                        }
                      }}
                    >
                      {t("worklog.void")}
                    </Button>
                  )}
                </div>
                <span className="text-muted-foreground text-xs">
                  {t("worklog.entryMeta", {
                    worker: entry.employee.name,
                    date: new Date(`${entry.worked_on}T00:00:00`).toLocaleDateString(i18n.language),
                    hours: hoursOf(entry.hours),
                    recorder: entry.recorded_by_name,
                  })}
                </span>
              </li>
            ))}
          </ul>
        )}
        {!closed && (
          <form className="grid gap-3 border-t pt-3 md:grid-cols-[2fr_1fr_1fr_1fr_auto] md:items-end" onSubmit={submit}>
            <Field
              id="work-description"
              label={t("worklog.description")}
              required
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
            <div className="grid gap-1.5">
              <Label htmlFor="work-worker">{t("worklog.doneBy")}</Label>
              <Select id="work-worker" value={worker} onChange={(event) => setWorker(event.target.value)}>
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
              value={workedOn}
              onChange={(event) => setWorkedOn(event.target.value)}
            />
            <Field
              id="work-hours"
              inputMode="decimal"
              label={t("worklog.hours")}
              value={hours}
              onChange={(event) => setHours(event.target.value)}
            />
            <Button type="submit" disabled={action.isPending || !description.trim() || !workedOn}>
              {t("worklog.addWork")}
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

function NotesCard({
  orderId,
  log,
  onAdded,
}: {
  orderId: string;
  log: Worklog;
  onAdded: () => Promise<unknown>;
}) {
  const { t, i18n } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const [body, setBody] = useState("");
  const add = useMutation({
    mutationFn: () => worklogApi(workshopId, orderId).addNote(body),
    onSuccess: () => setBody(""),
    onSettled: onAdded,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("worklog.notes")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        <p className="text-muted-foreground text-xs">{t("worklog.notesHint")}</p>
        {log.notes.length > 0 && (
          <ol className="grid gap-2">
            {log.notes.map((note) => (
              <li key={note.seq} className="grid gap-0.5 border-l-2 pl-3">
                <span className="text-muted-foreground text-xs">
                  {note.employee_name} · {formatDateTime(note.created_at, i18n.language)}
                </span>
                <p className="text-sm whitespace-pre-line">{note.body}</p>
              </li>
            ))}
          </ol>
        )}
        {add.isError && (
          <p role="alert" className="text-destructive text-sm">
            {errorMessage(t, add.error)}
          </p>
        )}
        <form
          className="grid gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            add.mutate();
          }}
        >
          <Label htmlFor="note-body" className="sr-only">
            {t("worklog.newNote")}
          </Label>
          <Textarea
            id="note-body"
            placeholder={t("worklog.newNote")}
            value={body}
            onChange={(event) => setBody(event.target.value)}
          />
          <div>
            <Button type="submit" size="sm" disabled={add.isPending || !body.trim()}>
              {t("worklog.addNote")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
