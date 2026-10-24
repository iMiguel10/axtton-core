import { useEffect, useState } from "react";
import { ApiError, api, errorText } from "@/shared/api";
import { formatEur } from "@/shared/money";

/**
 * Portal del cliente, versión F0: la página que abre el enlace secreto
 * /portal/quotes/<taller>/<token>. Sin sesión; en F4 llegará el enlace mágico.
 */

type Line = {
  description: string;
  quantity: string;
  unit_price_cents: number;
  vat_bp: number;
  line_total_cents: number | null;
};

type Quote = { status: string; total_cents: number; lines: Line[] };

const STATUS_TEXT: Record<string, string> = {
  sent: "Pendiente de tu respuesta",
  approved: "Aprobado",
  rejected: "Rechazado",
};

/** La página es /portal/quotes/<taller>/<token>; la API, /api/v1 + lo mismo. */
function apiPathFromLocation(): string | null {
  const match = window.location.pathname.match(/^\/portal\/quotes\/([^/]+)\/([^/]+)\/?$/);
  return match ? `/api/v1/portal/quotes/${match[1]}/${match[2]}` : null;
}

export function PortalApp() {
  const apiPath = apiPathFromLocation();
  const [quote, setQuote] = useState<Quote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!apiPath) return;
    let ignore = false;
    api<Quote>(apiPath).then(
      (data) => {
        if (!ignore) setQuote(data);
      },
      (e: unknown) => {
        if (ignore) return;
        // Un enlace inventado, caducado o de otro taller da 404: el portal no
        // distingue entre ellos, igual que la API.
        setError(e instanceof ApiError && e.status === 404 ? "not_found" : errorText(e));
      },
    );
    return () => {
      ignore = true;
    };
  }, [apiPath, reloadKey]);

  async function decide(outcome: "approved" | "rejected") {
    try {
      await api<void>(`${apiPath}/decision`, {
        method: "POST",
        body: JSON.stringify({ outcome }),
      });
      setReloadKey((key) => key + 1);
    } catch (e) {
      setError(errorText(e));
    }
  }

  if (!apiPath || error === "not_found") {
    return (
      <main>
        <h1>Enlace no válido</h1>
        <p>Este enlace no existe o ya no está disponible. Pide al taller uno nuevo.</p>
      </main>
    );
  }
  if (!quote) {
    return <main>Cargando…</main>;
  }

  return (
    <main>
      <h1>Tu presupuesto</h1>
      <p>
        <strong>{STATUS_TEXT[quote.status] ?? quote.status}</strong>
      </p>
      {error && <p className="error">Error: {error}</p>}
      <table>
        <thead>
          <tr>
            <th>Concepto</th>
            <th className="num">Importe (IVA incl.)</th>
          </tr>
        </thead>
        <tbody>
          {quote.lines.map((line, i) => (
            <tr key={i}>
              <td>{line.description}</td>
              <td className="num">{formatEur(line.line_total_cents ?? 0)}</td>
            </tr>
          ))}
          <tr>
            <td>
              <strong>Total</strong>
            </td>
            <td className="num">
              <strong>{formatEur(quote.total_cents)}</strong>
            </td>
          </tr>
        </tbody>
      </table>
      <div className="box">
        {quote.status === "sent" && (
          <>
            <button onClick={() => decide("approved")}>Aprobar</button>
            <button onClick={() => decide("rejected")}>Rechazar</button>
          </>
        )}
        {/* Este PDF no necesita cabeceras: el enlace ya lleva taller y token. */}
        <a href={`${apiPath}/pdf`} target="_blank" rel="noreferrer">
          Ver el presupuesto en PDF
        </a>
      </div>
    </main>
  );
}
