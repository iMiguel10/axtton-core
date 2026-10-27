import { useQuery } from "@tanstack/react-query";
import { Car, CornerDownLeft, Plus, Search, UserRound, type LucideIcon } from "lucide-react";
import { useEffect, useId, useMemo, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { Button } from "@/shared/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/shared/components/ui/dialog";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";
import { cn } from "@/shared/lib/utils";

import { clientName } from "../clients/clientName";
import { search } from "../home/api";
import { useActiveWorkshop } from "../session/ActiveWorkshop";
import type { NavGroup } from "./AppLayout";

type Item = { id: string; group: string; label: string; hint?: string; icon: LucideIcon; to: string };

export type PaletteAction = { to: string; label: string };

/**
 * Buscar e ir a cualquier sitio desde cualquier pantalla (Ctrl+K o Cmd+K): una
 * matrícula, un cliente, un teléfono, un apartado o una acción ("Abrir orden").
 * Con el teclado de principio a fin: flechas para elegir, Intro para ir, Escape
 * para cerrar. La búsqueda es la del mostrador (RF-14).
 *
 * Es un combobox con su listbox (ARIA): el foco se queda en la caja y la opción
 * marcada se anuncia con `aria-activedescendant`.
 */
export function CommandPalette({ groups, actions }: { groups: NavGroup[]; actions: PaletteAction[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function onKey(event: globalThis.KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((value) => !value);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="text-muted-foreground ml-auto w-9 justify-start gap-2 px-2 sm:w-56"
        onClick={() => setOpen(true)}
        aria-label={t("palette.open")}
      >
        <Search />
        <span className="hidden flex-1 text-left sm:inline">{t("palette.placeholderShort")}</span>
        <kbd className="bg-muted hidden rounded px-1.5 text-[10px] font-medium sm:inline">Ctrl K</kbd>
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent showCloseButton={false} className="top-[15%] translate-y-0 gap-0 p-0 sm:max-w-lg">
          {/* Se monta al abrir: cada vez empieza en blanco. */}
          {open && <Palette groups={groups} actions={actions} onDone={() => setOpen(false)} />}
        </DialogContent>
      </Dialog>
    </>
  );
}

function Palette({
  groups,
  actions,
  onDone,
}: {
  groups: NavGroup[];
  actions: PaletteAction[];
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { workshopId } = useActiveWorkshop();
  const listId = useId();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const q = useDebouncedValue(query.trim(), 200);
  const results = useQuery({
    queryKey: ["search", workshopId, q],
    queryFn: () => search(workshopId, q),
    enabled: q.length > 0,
    placeholderData: (previous) => previous,
  });

  const items = useMemo<Item[]>(() => {
    const needle = query.trim().toLowerCase();
    const matches = (label: string) => !needle || label.toLowerCase().includes(needle);
    const go: Item[] = groups
      .flatMap((group) => group.items)
      .filter((item) => matches(item.label))
      .map((item) => ({ id: `nav:${item.to}`, group: t("palette.goTo"), label: item.label, icon: item.icon, to: item.to }));
    const doing: Item[] = actions
      .filter((action) => matches(action.label))
      .map((action) => ({ id: `do:${action.to}`, group: t("palette.actions"), label: action.label, icon: Plus, to: action.to }));
    const found = q && results.data ? results.data : { vehicles: [], clients: [] };
    const vehicles: Item[] = found.vehicles.map((vehicle) => ({
      id: `v:${vehicle.id}`,
      group: t("home.vehicles"),
      label: vehicle.plate,
      hint: [vehicle.make, vehicle.model, vehicle.owner ? clientName(t, vehicle.owner.name) : null]
        .filter(Boolean)
        .join(" · "),
      icon: Car,
      to: `/vehicles/${vehicle.id}`,
    }));
    const clients: Item[] = found.clients.map((client) => ({
      id: `c:${client.id}`,
      group: t("home.clients"),
      label: clientName(t, client.name),
      hint: client.phone,
      icon: UserRound,
      to: `/clients/${client.id}`,
    }));
    // Lo encontrado primero: si se ha escrito algo, es lo que se busca.
    return needle ? [...vehicles, ...clients, ...doing, ...go] : [...doing, ...go];
  }, [query, q, results.data, groups, actions, t]);

  const selected = Math.min(active, Math.max(items.length - 1, 0));
  function choose(item: Item | undefined) {
    if (!item) return;
    onDone();
    navigate(item.to);
  }
  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((selected + 1) % Math.max(items.length, 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((selected - 1 + items.length) % Math.max(items.length, 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(items[selected]);
    }
  }

  return (
    <>
      <DialogTitle className="sr-only">{t("palette.open")}</DialogTitle>
      <div className="flex items-center gap-2 border-b px-3">
        <Search className="text-muted-foreground size-4 shrink-0" />
        <input
          autoFocus
          role="combobox"
          aria-expanded="true"
          aria-controls={listId}
          aria-activedescendant={items[selected] ? `${listId}-${items[selected].id}` : undefined}
          aria-label={t("palette.open")}
          className="placeholder:text-muted-foreground h-12 flex-1 bg-transparent text-base outline-none md:text-sm"
          placeholder={t("palette.placeholder")}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
        />
      </div>
      <ul id={listId} role="listbox" aria-label={t("palette.results")} className="max-h-80 overflow-y-auto p-2">
        {items.length === 0 ? (
          <li className="text-muted-foreground px-3 py-6 text-center text-sm">
            {results.isFetching ? t("common.loading") : t("home.noResults")}
          </li>
        ) : (
          items.map((item, index) => (
            <li key={item.id} role="presentation">
              {(index === 0 || items[index - 1].group !== item.group) && (
                <div className="text-muted-foreground px-2 pt-2 pb-1 text-xs font-medium">{item.group}</div>
              )}
              <div
                id={`${listId}-${item.id}`}
                role="option"
                aria-selected={index === selected}
                className={cn(
                  "flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2",
                  index === selected && "bg-muted",
                )}
                onMouseMove={() => setActive(index)}
                onClick={() => choose(item)}
              >
                <item.icon className="text-muted-foreground size-4 shrink-0" />
                <span className="truncate font-medium">{item.label}</span>
                {item.hint && <span className="text-muted-foreground truncate text-xs">{item.hint}</span>}
                {index === selected && <CornerDownLeft className="text-muted-foreground ml-auto size-3.5 shrink-0" />}
              </div>
            </li>
          ))
        )}
      </ul>
    </>
  );
}
