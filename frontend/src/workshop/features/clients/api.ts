import { apiRequest } from "@/shared/lib/apiClient";

export type ClientKind = "individual" | "company";
export type Language = "es" | "en";

export type Client = {
  id: string;
  kind: ClientKind;
  name: string;
  tax_id: string | null;
  phone: string;
  email: string | null;
  address: string | null;
  notes: string | null;
  language: Language;
  archived_at: string | null;
  created_at: string;
  /** Se devuelve al editar: bloqueo optimista (RNF-15). */
  version: number;
};

export type ClientInput = {
  kind: ClientKind;
  name: string;
  tax_id: string | null;
  phone: string;
  email: string | null;
  address: string | null;
  notes: string | null;
  language: Language;
};

export type ClientFilters = { q: string; archived: boolean };

export const PAGE_SIZE = 50;

export function clientsApi(workshopId: string) {
  const request = <T>(path: string, method: "GET" | "POST" | "PATCH", body?: unknown) =>
    apiRequest<T>(`/workshop/clients${path}`, { method, body, workshopId });
  return {
    list: ({ q, archived }: ClientFilters, offset: number) => {
      const params = new URLSearchParams({
        archived: String(archived),
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      if (q.trim()) params.set("q", q.trim());
      return request<Client[]>(`?${params}`, "GET");
    },
    get: (id: string) => request<Client>(`/${id}`, "GET"),
    create: (input: ClientInput) => request<{ id: string }>("", "POST", input),
    update: (client: Client, changes: Partial<ClientInput>) =>
      request<void>(`/${client.id}`, "PATCH", { version: client.version, ...changes }),
    setArchived: (client: Client, archived: boolean) =>
      request<void>(`/${client.id}/${archived ? "archive" : "unarchive"}`, "POST", {
        version: client.version,
      }),
  };
}
