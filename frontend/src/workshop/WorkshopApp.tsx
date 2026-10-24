import { useEffect, useState } from "react";
import { api, errorText, openPdf } from "@/shared/api";
import { formatEur, parseEurToCents } from "@/shared/money";

/**
 * Aplicación del taller, versión F0: sin autenticación, el taller se escribe a
 * mano. En F1 lo dará la sesión y un selector de talleres.
 */

type WorkOrder = {
  id: string;
  status: string;
  client_name: string;
  plate: string;
  quote_id: string | null;
  quote_status: string | null;
};

type QuoteSent = { quote_id: string; total_cents: number; approval_url: string };

const STORAGE_KEY = "f0.workshopId";

export function WorkshopApp() {
  const [workshopId, setWorkshopId] = useState(
    () => localStorage.getItem(STORAGE_KEY) ?? "",
  );
  const [orders, setOrders] = useState<WorkOrder[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [lastSent, setLastSent] = useState<QuoteSent | null>(null);
  // Subirlo fuerza a recargar las órdenes (tras enviar un presupuesto).
  const [reloadKey, setReloadKey] = useState(0);

  // Todas las peticiones del taller llevan el taller activo en la cabecera (A6).
  const headers = { "X-Workshop-Id": workshopId };

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, workshopId);
    if (!workshopId) return;
    // Si el taller cambia antes de que llegue la respuesta (se está escribiendo
    // el id letra a letra), la respuesta vieja se descarta: sin esto, una
    // respuesta lenta podría pisar a la buena.
    let ignore = false;
    api<WorkOrder[]>("/api/v1/workshop/work-orders", {
      headers: { "X-Workshop-Id": workshopId },
    }).then(
      (data) => {
        if (ignore) return;
        setOrders(data);
        setError(null);
      },
      (e: unknown) => {
        if (!ignore) setError(errorText(e));
      },
    );
    return () => {
      ignore = true;
    };
  }, [workshopId, reloadKey]);

  async function createAndSend(order: WorkOrder, description: string, price: string) {
    const unitPriceCents = parseEurToCents(price);
    if (unitPriceCents === null) {
      setError("Precio no válido: usa 85,50");
      return;
    }
    try {
      setError(null);
      const { quote_id } = await api<{ quote_id: string }>(
        `/api/v1/workshop/work-orders/${order.id}/quotes`,
        {
          method: "POST",
          headers,
          body: JSON.stringify({
            description,
            quantity: "1",
            unit_price_cents: unitPriceCents,
          }),
        },
      );
      setLastSent(
        await api<QuoteSent>(`/api/v1/workshop/quotes/${quote_id}/send`, {
          method: "POST",
          headers,
        }),
      );
      setReloadKey((key) => key + 1);
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <main>
      <h1>AXTTON CORE · Taller (F0)</h1>
      <label>
        Taller activo (id, sin autenticación en F0):{" "}
        <input
          size={40}
          value={workshopId}
          onChange={(e) => setWorkshopId(e.target.value.trim())}
          placeholder="pega el id que imprime seed_f0"
        />
      </label>
      {error && <p className="error">Error: {error}</p>}

      {lastSent && (
        <div className="box">
          <strong>Presupuesto enviado: {formatEur(lastSent.total_cents)}</strong>
          <p className="muted">
            En F5 este enlace le llegará al cliente por email. En F0 se muestra aquí:
          </p>
          <a href={lastSent.approval_url} target="_blank" rel="noreferrer">
            Abrir el portal del cliente
          </a>
        </div>
      )}

      <table>
        <thead>
          <tr>
            <th>Matrícula</th>
            <th>Cliente</th>
            <th>Estado</th>
            <th>Presupuesto</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => (
            <OrderRow
              key={order.id}
              order={order}
              onSend={createAndSend}
              onPdf={(quoteId) =>
                openPdf(`/api/v1/workshop/quotes/${quoteId}/pdf`, headers).catch(
                  (e: unknown) => setError(errorText(e)),
                )
              }
            />
          ))}
        </tbody>
      </table>
    </main>
  );
}

function OrderRow({
  order,
  onSend,
  onPdf,
}: {
  order: WorkOrder;
  onSend: (order: WorkOrder, description: string, price: string) => void;
  onPdf: (quoteId: string) => void;
}) {
  const [description, setDescription] = useState("Cambio de pastillas de freno");
  const [price, setPrice] = useState("85,50");

  return (
    <tr>
      <td>{order.plate}</td>
      <td>{order.client_name}</td>
      <td>{order.status}</td>
      <td>
        {order.quote_id ? (
          <>
            {order.quote_status}{" "}
            <button onClick={() => onPdf(order.quote_id!)}>PDF</button>
          </>
        ) : (
          <>
            <input value={description} onChange={(e) => setDescription(e.target.value)} />{" "}
            <input
              size={6}
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              aria-label="Precio sin IVA"
            />{" "}
            € + IVA{" "}
            <button onClick={() => onSend(order, description, price)}>
              Crear y enviar
            </button>
          </>
        )}
      </td>
    </tr>
  );
}
