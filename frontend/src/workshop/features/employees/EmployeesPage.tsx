import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { Field } from "@/shared/components/form/Field";
import { Select } from "@/shared/components/form/Select";
import { Badge } from "@/shared/components/ui/badge";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { Input } from "@/shared/components/ui/input";
import { Label } from "@/shared/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/shared/components/ui/table";
import { errorMessage } from "@/shared/lib/errors";
import { formatEur, parseEurToCents } from "@/shared/money";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import type { Role } from "../session/api";
import { employeesApi, type Employee } from "./api";

const ROLES: Role[] = ["admin", "mechanic"];

/** Empleados del taller activo (RF-03 a RF-06). Solo llega aquí quien puede gestionarlos. */
export function EmployeesPage() {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const api = employeesApi(workshopId);
  const queryClient = useQueryClient();
  const queryKey = ["employees", workshopId];
  const employees = useQuery({ queryKey, queryFn: api.list });
  const [notice, setNotice] = useState<string | null>(null);

  // Una sola mutación para todas las acciones de fila: el error (un 409 si otro
  // administrador cambió la ficha, last_admin...) se enseña arriba, y al terminar
  // se vuelve a pedir la lista para tener las versiones al día.
  const action = useMutation({
    mutationFn: (run: () => Promise<unknown>) => run(),
    onMutate: () => setNotice(null),
    onSettled: () => queryClient.invalidateQueries({ queryKey }),
  });

  return (
    <section className="grid gap-6">
      <h1 className="text-2xl font-semibold">{t("employees.title")}</h1>
      <NewEmployeeForm
        onCreate={async (input) => {
          await api.create(input);
          await queryClient.invalidateQueries({ queryKey });
        }}
      />
      {action.isError && (
        <p role="alert" className="text-destructive text-sm">
          {errorMessage(t, action.error)}
        </p>
      )}
      {notice && <p role="status" className="text-sm">{notice}</p>}
      {employees.isPending ? (
        <p>{t("common.loading")}</p>
      ) : employees.isError ? (
        <p role="alert">{errorMessage(t, employees.error)}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("employees.name")}</TableHead>
              <TableHead>{t("employees.role")}</TableHead>
              <TableHead>{t("employees.status")}</TableHead>
              <TableHead>{t("employees.hourlyCost")}</TableHead>
              <TableHead>
                <span className="sr-only">{t("common.actions")}</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {employees.data.map((employee) => (
              <EmployeeRow
                key={employee.id}
                employee={employee}
                busy={action.isPending}
                onChangeRole={(role) => action.mutate(() => api.update(employee, { role }))}
                onToggleActive={() =>
                  action.mutate(() => api.update(employee, { active: !employee.active }))
                }
                onRemoveAccess={() => {
                  if (window.confirm(t("employees.confirmRemoveAccess", { name: employee.name }))) {
                    action.mutate(() => api.removeAccess(employee));
                  }
                }}
                onInvite={(email) =>
                  action.mutate(async () => {
                    const result = await api.invite(employee, email);
                    setNotice(
                      t(result.invitation_email_queued ? "employees.invited" : "employees.invitedNoEmail", {
                        email,
                      }),
                    );
                  })
                }
              />
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  );
}

function EmployeeRow({
  employee,
  busy,
  onChangeRole,
  onToggleActive,
  onRemoveAccess,
  onInvite,
}: {
  employee: Employee;
  busy: boolean;
  onChangeRole: (role: Role) => void;
  onToggleActive: () => void;
  onRemoveAccess: () => void;
  onInvite: (email: string) => void;
}) {
  const { t } = useTranslation();
  const [inviting, setInviting] = useState(false);
  const [email, setEmail] = useState("");

  return (
    <TableRow>
      <TableCell>
        <div className="font-medium">{employee.name}</div>
        {employee.position && (
          <div className="text-muted-foreground text-xs">{employee.position}</div>
        )}
      </TableCell>
      <TableCell>
        <Select
          aria-label={t("employees.roleOf", { name: employee.name })}
          value={employee.role}
          disabled={busy}
          onChange={(event) => onChangeRole(event.target.value as Role)}
        >
          {ROLES.map((role) => (
            <option key={role} value={role}>
              {t(`roles.${role}`)}
            </option>
          ))}
        </Select>
      </TableCell>
      <TableCell className="flex flex-wrap gap-1">
        <Badge variant={employee.active ? "success" : "secondary"}>
          {t(employee.active ? "employees.active" : "employees.inactive")}
        </Badge>
        {employee.has_access ? (
          <Badge variant="outline">{t("employees.hasAccess")}</Badge>
        ) : employee.invitation_pending ? (
          <Badge variant="outline">{t("employees.invitationPending")}</Badge>
        ) : null}
      </TableCell>
      <TableCell>
        {employee.hourly_cost_cents === null ? "—" : formatEur(employee.hourly_cost_cents)}
      </TableCell>
      <TableCell>
        <div className="flex flex-wrap justify-end gap-1">
          <Button variant="outline" size="sm" disabled={busy} onClick={onToggleActive}>
            {t(employee.active ? "employees.deactivate" : "employees.activate")}
          </Button>
          {employee.has_access ? (
            <Button variant="outline" size="sm" disabled={busy} onClick={onRemoveAccess}>
              {t("employees.removeAccess")}
            </Button>
          ) : (
            employee.active &&
            !inviting && (
              <Button variant="outline" size="sm" disabled={busy} onClick={() => setInviting(true)}>
                {t(employee.invitation_pending ? "employees.reinvite" : "employees.invite")}
              </Button>
            )
          )}
        </div>
        {inviting && (
          <form
            className="mt-2 flex gap-1"
            onSubmit={(event) => {
              event.preventDefault();
              onInvite(email);
              setInviting(false);
              setEmail("");
            }}
          >
            <Input
              type="email"
              required
              // Aparece al pulsar Invitar: el foco va a donde hay que escribir.
              autoFocus
              aria-label={t("employees.inviteEmail", { name: employee.name })}
              placeholder={t("auth.email")}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
            <Button type="submit" size="sm" disabled={busy}>
              {t("employees.send")}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setInviting(false)}>
              {t("common.cancel")}
            </Button>
          </form>
        )}
      </TableCell>
    </TableRow>
  );
}

const newEmployeeSchema = z.object({
  name: z.string().trim().min(1, "validation.required").max(200),
  position: z.string().trim().max(100),
  role: z.enum(["admin", "mechanic"]),
  hourlyCost: z
    .string()
    .refine((value) => value.trim() === "" || parseEurToCents(value) !== null, "validation.amount"),
});
type NewEmployee = z.infer<typeof newEmployeeSchema>;

function NewEmployeeForm({
  onCreate,
}: {
  onCreate: (input: {
    name: string;
    position: string | null;
    role: Role;
    hourly_cost_cents: number | null;
  }) => Promise<void>;
}) {
  const { t } = useTranslation();
  const form = useForm<NewEmployee>({
    resolver: zodResolver(newEmployeeSchema),
    defaultValues: { name: "", position: "", role: "mechanic", hourlyCost: "" },
  });
  const { errors } = form.formState;
  const create = useMutation({
    mutationFn: (values: NewEmployee) =>
      onCreate({
        name: values.name,
        position: values.position || null,
        role: values.role,
        hourly_cost_cents: values.hourlyCost.trim() ? parseEurToCents(values.hourlyCost) : null,
      }),
    onSuccess: () => form.reset(),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("employees.new")}</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-4 md:grid-cols-[2fr_2fr_1fr_1fr_auto] md:items-end"
          onSubmit={form.handleSubmit((values) => create.mutate(values))}
          noValidate
        >
          <Field
            id="new-name"
            label={t("employees.name")}
            error={errors.name && t(errors.name.message ?? "")}
            {...form.register("name")}
          />
          <Field id="new-position" label={t("employees.position")} {...form.register("position")} />
          <div className="grid gap-1.5">
            <Label htmlFor="new-role">{t("employees.role")}</Label>
            <Select id="new-role" {...form.register("role")}>
              {ROLES.map((role) => (
                <option key={role} value={role}>
                  {t(`roles.${role}`)}
                </option>
              ))}
            </Select>
          </div>
          <Field
            id="new-cost"
            inputMode="decimal"
            label={t("employees.hourlyCost")}
            error={errors.hourlyCost && t(errors.hourlyCost.message ?? "")}
            {...form.register("hourlyCost")}
          />
          <Button type="submit" disabled={create.isPending}>
            {t("employees.create")}
          </Button>
        </form>
        {create.isError && (
          <p role="alert" className="text-destructive mt-2 text-sm">
            {errorMessage(t, create.error)}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
