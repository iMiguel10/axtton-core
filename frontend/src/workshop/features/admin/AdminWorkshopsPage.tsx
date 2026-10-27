import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { TableSkeleton } from "@/shared/components/Loading";
import { Field } from "@/shared/components/form/Field";
import { Badge } from "@/shared/components/ui/badge";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { Input } from "@/shared/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/shared/components/ui/table";
import { errorMessage } from "@/shared/lib/errors";

import { adminApi, type WorkshopSummary } from "./api";

const queryKey = ["admin", "workshops"];

/** Talleres de la instalación (RF-112, RF-113). El superadministrador no ve su operativa. */
export function AdminWorkshopsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const workshops = useQuery({ queryKey, queryFn: adminApi.list });
  const me = useQuery({ queryKey: ["admin", "me"], queryFn: adminApi.me });
  // Taller único (RF-111): una vez creado, el alta desaparece. La API lo rechaza
  // igual; esto evita ofrecer algo que solo puede acabar en error.
  const canCreate =
    me.data?.installation_mode !== "single" || (workshops.data?.length ?? 0) === 0;
  const update = useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: Parameters<typeof adminApi.update>[1] }) =>
      adminApi.update(id, changes),
    onSettled: () => queryClient.invalidateQueries({ queryKey }),
  });

  return (
    <section className="grid gap-6">
      {me.isSuccess && workshops.isSuccess && canCreate && <NewWorkshopForm />}
      {me.isSuccess && workshops.isSuccess && !canCreate && (
        <p className="text-muted-foreground text-sm">{t("admin.singleInstallation")}</p>
      )}
      {update.isError && (
        <p role="alert" className="text-destructive text-sm">
          {errorMessage(t, update.error)}
        </p>
      )}
      {workshops.isPending ? (
        <TableSkeleton />
      ) : workshops.isError ? (
        <p role="alert">{errorMessage(t, workshops.error)}</p>
      ) : (
        <Card>
          <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("admin.workshop")}</TableHead>
              <TableHead>{t("admin.admins")}</TableHead>
              <TableHead>{t("admin.status")}</TableHead>
              <TableHead>{t("admin.access")}</TableHead>
              <TableHead>{t("admin.pendingInvitations")}</TableHead>
              <TableHead>{t("admin.limit")}</TableHead>
              <TableHead>
                <span className="sr-only">{t("common.actions")}</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {workshops.data.map((workshop) => (
              <WorkshopRow
                key={workshop.id}
                workshop={workshop}
                busy={update.isPending}
                onUpdate={(changes) => update.mutate({ id: workshop.id, changes })}
              />
            ))}
          </TableBody>
        </Table>
  </CardContent>
</Card>
      )}
    </section>
  );
}

function WorkshopRow({
  workshop,
  busy,
  onUpdate,
}: {
  workshop: WorkshopSummary;
  busy: boolean;
  onUpdate: (changes: Parameters<typeof adminApi.update>[1]) => void;
}) {
  const { t } = useTranslation();
  const [limit, setLimit] = useState(String(workshop.max_employees_with_access));
  const active = workshop.status === "active";
  const parsedLimit = Number(limit);
  const limitChanged =
    Number.isInteger(parsedLimit) &&
    parsedLimit >= 1 &&
    parsedLimit !== workshop.max_employees_with_access;

  return (
    <TableRow>
      <TableCell className="font-medium">{workshop.name}</TableCell>
      <TableCell>{workshop.admins.length ? workshop.admins.join(", ") : "—"}</TableCell>
      <TableCell>
        <Badge variant={active ? "success" : "secondary"}>{t(`admin.statuses.${workshop.status}`)}</Badge>
      </TableCell>
      <TableCell>
        {workshop.employees_with_access} / {workshop.max_employees_with_access}
      </TableCell>
      <TableCell>{workshop.pending_invitations}</TableCell>
      <TableCell>
        <form
          className="flex gap-1"
          onSubmit={(event) => {
            event.preventDefault();
            if (limitChanged) onUpdate({ max_employees_with_access: parsedLimit });
          }}
        >
          <Input
            type="number"
            min={1}
            max={1000}
            className="w-20"
            aria-label={t("admin.limitOf", { name: workshop.name })}
            value={limit}
            onChange={(event) => setLimit(event.target.value)}
          />
          <Button type="submit" size="sm" variant="outline" disabled={busy || !limitChanged}>
            {t("common.save")}
          </Button>
        </form>
      </TableCell>
      <TableCell className="text-right">
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => onUpdate({ status: active ? "inactive" : "active" })}
        >
          {t(active ? "admin.deactivate" : "admin.activate")}
        </Button>
      </TableCell>
    </TableRow>
  );
}

const newWorkshopSchema = z.object({
  name: z.string().trim().min(1, "validation.required").max(200),
  admin_name: z.string().trim().min(1, "validation.required").max(200),
  admin_email: z.email("validation.email"),
});
type NewWorkshopForm = z.infer<typeof newWorkshopSchema>;

function NewWorkshopForm() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const form = useForm<NewWorkshopForm>({
    resolver: zodResolver(newWorkshopSchema),
    defaultValues: { name: "", admin_name: "", admin_email: "" },
  });
  const { errors } = form.formState;
  const create = useMutation({
    mutationFn: adminApi.create,
    onSuccess: () => {
      form.reset();
      void queryClient.invalidateQueries({ queryKey });
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("admin.new")}</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-4 md:grid-cols-[1fr_1fr_1fr_auto] md:items-end"
          onSubmit={form.handleSubmit((values) => create.mutate(values))}
          noValidate
        >
          <Field
            id="workshop-name"
            label={t("admin.workshopName")}
            error={errors.name && t(errors.name.message ?? "")}
            {...form.register("name")}
          />
          <Field
            id="admin-name"
            label={t("admin.adminName")}
            error={errors.admin_name && t(errors.admin_name.message ?? "")}
            {...form.register("admin_name")}
          />
          <Field
            id="admin-email"
            type="email"
            label={t("admin.adminEmail")}
            error={errors.admin_email && t(errors.admin_email.message ?? "")}
            {...form.register("admin_email")}
          />
          <Button type="submit" disabled={create.isPending}>
            {t("admin.create")}
          </Button>
        </form>
        {create.isError && (
          <p role="alert" className="text-destructive mt-2 text-sm">
            {errorMessage(t, create.error)}
          </p>
        )}
        {create.isSuccess && (
          <p role="status" className="mt-2 text-sm">
            {t(create.data.invitation_email_sent ? "admin.created" : "admin.createdNoEmail")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
