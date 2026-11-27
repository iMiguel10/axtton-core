import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Field } from "@/shared/components/form/Field";
import { TableSkeleton } from "@/shared/components/Loading";
import { notify } from "@/shared/components/Toaster";
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
import { useDates } from "@/shared/lib/dates";
import { errorMessage } from "@/shared/lib/errors";
import { formatEur, parseEurToCents } from "@/shared/money";
import {
  formatQuantity,
  formatSignedQuantity,
  parseQuantity,
  parseQuantityOrZero,
  parseSignedQuantity,
} from "@/shared/quantity";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { REVERSIBLE, stockApi, type Movement, type Part, type StockAlert } from "./api";

/** La incidencia de stock de una pieza (RF-94, RF-95). */
export function StockAlertBadge({ alert }: { alert: StockAlert | null }) {
  const { t } = useTranslation();
  if (alert === null) return null;
  return alert === "negative" ? (
    <Badge variant="destructive">{t("stock.alerts.negative")}</Badge>
  ) : (
    <Badge className="bg-status-waiting-parts/10 text-status-waiting-parts">
      {t("stock.alerts.below_minimum")}
    </Badge>
  );
}

type Mode = "entry" | "adjust" | "count";

/**
 * El stock de una pieza que se cuenta (F7 paso 2): lo que hay, las entradas,
 * ajustes y recuentos del administrador, y el historial (RF-96). El navegador
 * no calcula el stock: lo da la API como la suma de los movimientos.
 */
export function StockCard({ part }: { part: Part }) {
  const { t } = useTranslation();
  const { workshopId, canManageStock } = useActiveWorkshop();
  const [mode, setMode] = useState<Mode | null>(null);
  const queryClient = useQueryClient();
  // Lo que cambia con un movimiento: la ficha, el listado y el historial.
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["part", workshopId, part.id] }),
      queryClient.invalidateQueries({ queryKey: ["parts", workshopId] }),
      queryClient.invalidateQueries({ queryKey: ["part-movements", workshopId, part.id] }),
    ]);
  const stock = part.stock ?? "0";

  return (
    <Card>
      <CardHeader className="flex flex-wrap items-center gap-3">
        <CardTitle>{t("stock.title")}</CardTitle>
        <span className="text-2xl font-semibold tabular-nums">{formatQuantity(stock)}</span>
        <StockAlertBadge alert={part.stock_alert} />
        {part.min_stock !== null && (
          <span className="text-muted-foreground text-sm">
            {t("stock.minimum", { quantity: formatQuantity(part.min_stock) })}
          </span>
        )}
      </CardHeader>
      <CardContent className="grid gap-4">
        {canManageStock && !part.archived_at && (
          <div className="flex flex-wrap gap-2">
            {(["entry", "adjust", "count"] as const).map((each) => (
              <Button
                key={each}
                size="sm"
                variant={mode === each ? "default" : "outline"}
                onClick={() => setMode(mode === each ? null : each)}
              >
                {t(`stock.actions.${each}`)}
              </Button>
            ))}
          </div>
        )}
        {mode !== null && (
          <MovementForm
            // Con otro stock, el formulario vuelve a empezar: el recuento compara con él.
            key={`${mode}-${stock}`}
            mode={mode}
            part={part}
            stock={stock}
            onDone={() => setMode(null)}
            refresh={refresh}
          />
        )}
        <History part={part} refresh={refresh} />
      </CardContent>
    </Card>
  );
}

function MovementForm({
  mode,
  part,
  stock,
  onDone,
  refresh,
}: {
  mode: Mode;
  part: Part;
  stock: string;
  onDone: () => void;
  refresh: () => Promise<unknown>;
}) {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const api = stockApi(workshopId);
  const [quantity, setQuantity] = useState("");
  const [cost, setCost] = useState("");
  const [note, setNote] = useState("");
  const [invalid, setInvalid] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => {
      const trimmed = note.trim();
      if (mode === "entry") {
        return api.entry(part.id, {
          quantity: parseQuantity(quantity)!,
          unit_cost_cents: parseEurToCents(cost)!,
          note: trimmed || null,
        });
      }
      if (mode === "adjust") {
        return api.adjust(part.id, { quantity: parseSignedQuantity(quantity)!, note: trimmed });
      }
      // Lo contado, contra el stock que se ve en pantalla.
      return api.count(part.id, {
        counted: parseQuantityOrZero(quantity)!,
        expected: stock,
        note: trimmed || null,
      });
    },
    onSuccess: (created) => {
      notify(t(created.id === null ? "stock.countMatches" : "stock.saved"));
      onDone();
    },
    // También tras un 409: así se ve el stock que hay ahora.
    onSettled: refresh,
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const parsed =
      mode === "entry"
        ? parseQuantity(quantity)
        : mode === "adjust"
          ? parseSignedQuantity(quantity)
          : parseQuantityOrZero(quantity);
    if (parsed === null) return setInvalid("quantity");
    if (mode === "entry" && parseEurToCents(cost) === null) return setInvalid("cost");
    if (mode === "adjust" && !note.trim()) return setInvalid("note");
    setInvalid(null);
    save.mutate();
  };

  return (
    <form className="bg-muted/40 grid gap-3 rounded-lg p-3 md:grid-cols-3" onSubmit={submit} noValidate>
      <p className="text-muted-foreground text-sm md:col-span-3">{t(`stock.hints.${mode}`)}</p>
      <Field
        id="stock-quantity"
        inputMode="decimal"
        label={t(`stock.quantity.${mode}`)}
        value={quantity}
        onChange={(event) => setQuantity(event.target.value)}
        error={invalid === "quantity" ? t(mode === "adjust" ? "validation.signedQuantity" : "validation.quantity") : undefined}
      />
      {mode === "entry" && (
        <Field
          id="stock-cost"
          inputMode="decimal"
          label={t("stock.unitCost")}
          value={cost}
          onChange={(event) => setCost(event.target.value)}
          error={invalid === "cost" ? t("validation.amount") : undefined}
        />
      )}
      <Field
        id="stock-note"
        label={t(mode === "adjust" ? "stock.reason" : "stock.noteOptional")}
        maxLength={500}
        value={note}
        onChange={(event) => setNote(event.target.value)}
        error={invalid === "note" ? t("validation.required") : undefined}
      />
      <div className="flex items-center gap-2 md:col-span-3">
        <Button type="submit" size="sm" disabled={save.isPending}>
          {t(`stock.save.${mode}`)}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDone}>
          {t("common.cancel")}
        </Button>
      </div>
      {save.isError && (
        <p role="alert" className="text-destructive text-sm md:col-span-3">
          {errorMessage(t, save.error)}
        </p>
      )}
    </form>
  );
}

/** El historial de movimientos de la pieza, del más reciente al más antiguo (RF-96). */
function History({ part, refresh }: { part: Part; refresh: () => Promise<unknown> }) {
  const { t } = useTranslation();
  const dates = useDates();
  const { workshopId, canManageStock, canViewCosts } = useActiveWorkshop();
  const api = stockApi(workshopId);
  const history = useInfiniteQuery({
    queryKey: ["part-movements", workshopId, part.id],
    queryFn: ({ pageParam }) => api.history(part.id, pageParam),
    initialPageParam: null as number | null,
    getNextPageParam: (last) => last.next_before,
  });
  const [reversing, setReversing] = useState<string | null>(null);

  if (history.isPending) return <TableSkeleton />;
  if (history.isError) return <p role="alert">{errorMessage(t, history.error)}</p>;
  const movements = history.data.pages.flatMap((page) => page.movements);
  if (movements.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("stock.noMovements")}</p>;
  }
  const canReverse = (movement: Movement) =>
    canManageStock && REVERSIBLE.includes(movement.kind) && movement.reversed_by_id === null;

  return (
    <div className="grid gap-2">
      <h3 className="text-sm font-medium">{t("stock.history")}</h3>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("stock.when")}</TableHead>
              <TableHead>{t("stock.what")}</TableHead>
              <TableHead className="text-right">{t("stock.quantityShort")}</TableHead>
              <TableHead>{t("stock.detail")}</TableHead>
              <TableHead>{t("stock.who")}</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {movements.map((movement) => (
              <TableRow key={movement.id}>
                <TableCell className="whitespace-nowrap">{dates.dateTime(movement.created_at)}</TableCell>
                <TableCell>
                  {t(`stock.kinds.${movement.kind}`)}
                  {movement.counted_stock !== null && ` · ${t("stock.counted", { quantity: formatQuantity(movement.counted_stock) })}`}
                  {movement.reversed_by_id !== null && (
                    <Badge variant="secondary" className="ml-2">
                      {t("stock.reversed")}
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatSignedQuantity(movement.quantity)}</TableCell>
                <TableCell className="text-sm">
                  {/* El origen de una salida o de su anulación: la orden (RF-96). */}
                  {movement.work_order_id !== null && (
                    <Link to={`/orders/${movement.work_order_id}`} className="link mr-1">
                      {movement.work_order_code}
                    </Link>
                  )}
                  {[
                    canViewCosts && movement.unit_cost_cents !== null
                      ? t("stock.atCost", { cost: formatEur(movement.unit_cost_cents) })
                      : null,
                    movement.note,
                  ]
                    .filter(Boolean)
                    .join(" · ") || (movement.work_order_id === null ? "—" : "")}
                </TableCell>
                <TableCell>{movement.employee_name}</TableCell>
                <TableCell className="text-right">
                  {canReverse(movement) && reversing !== movement.id && (
                    <Button size="sm" variant="ghost" onClick={() => setReversing(movement.id)}>
                      {t("stock.reverse")}
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {reversing !== null && (
        <ReverseForm
          key={reversing}
          movementId={reversing}
          onDone={() => setReversing(null)}
          refresh={refresh}
        />
      )}
      {history.hasNextPage && (
        <Button
          variant="outline"
          size="sm"
          className="justify-self-start"
          disabled={history.isFetchingNextPage}
          onClick={() => void history.fetchNextPage()}
        >
          {t("stock.loadMore")}
        </Button>
      )}
    </div>
  );
}

/** Anular una entrada o un ajuste mal anotados (RNF-12): con su motivo, y una vez. */
function ReverseForm({
  movementId,
  onDone,
  refresh,
}: {
  movementId: string;
  onDone: () => void;
  refresh: () => Promise<unknown>;
}) {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const [note, setNote] = useState("");
  const reverse = useMutation({
    mutationFn: () => stockApi(workshopId).reverse(movementId, note.trim()),
    onSuccess: () => {
      notify(t("stock.reversedDone"));
      onDone();
    },
    onSettled: refresh,
  });
  return (
    <form
      className="bg-muted/40 grid gap-2 rounded-lg p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (note.trim()) reverse.mutate();
      }}
    >
      <p className="text-sm">{t("stock.reverseHint")}</p>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          aria-label={t("stock.reason")}
          placeholder={t("stock.reason")}
          maxLength={500}
          className="max-w-md"
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
        <Button type="submit" size="sm" disabled={reverse.isPending || !note.trim()}>
          {t("stock.reverse")}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDone}>
          {t("common.cancel")}
        </Button>
      </div>
      {reverse.isError && (
        <p role="alert" className="text-destructive text-sm">
          {errorMessage(t, reverse.error)}
        </p>
      )}
    </form>
  );
}
