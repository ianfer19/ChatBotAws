import type { ChatTrace, StateResponse } from "../types";

interface Props {
  trace: ChatTrace | null;
  business: StateResponse | null;
  llmMode: string | null;
}

function confidence(value: number | null): string {
  if (value === null) {
    return "—";
  }
  return `${Math.round(value * 100)}%`;
}

export default function TracePanel({ trace, business, llmMode }: Props) {
  return (
    <aside className="trace-card">
      <section className="panel">
        <header className="panel-header">
          <div>
            <h2 className="panel-title">Traza del último turno</h2>
            <p className="panel-sub">Lo que el grafo decidió, sin inventar nada.</p>
          </div>
        </header>
        <div className="panel-body">
          {trace === null ? (
            <div className="empty">
              <div className="empty-icon">◎</div>
              <span className="small">
                Envía un mensaje para ver intención, destino, latencia y estado.
              </span>
            </div>
          ) : (
            <div className="trace-grid">
              <div className="trace-item">
                <span className="trace-label">Intención</span>
                <span className="trace-value">
                  <span className="pill pill-neutral">{trace.intent ?? "—"}</span>{" "}
                  <span className="muted small">
                    confianza {confidence(trace.confidence)}
                  </span>
                </span>
              </div>

              <div className="trace-item">
                <span className="trace-label">Destino</span>
                <span className="trace-value">
                  <span className="pill">{trace.target ?? "sin destino"}</span>
                </span>
              </div>

              {trace.route_error ? (
                <div className="trace-item">
                  <span className="trace-label">Error de ruta</span>
                  <span className="trace-value">
                    <span className="pill pill-danger">{trace.route_error}</span>
                  </span>
                </div>
              ) : null}

              {trace.pending_outcome ? (
                <div className="trace-item">
                  <span className="trace-label">Draft resuelto</span>
                  <span className="trace-value">
                    <span className="pill pill-ok">{trace.pending_outcome}</span>
                  </span>
                </div>
              ) : null}

              {trace.notice ? (
                <div className="trace-item">
                  <span className="trace-label">Aviso</span>
                  <span className="trace-value">{trace.notice}</span>
                </div>
              ) : null}

              <div className="trace-item">
                <span className="trace-label">Latencia</span>
                <span className="trace-value">{trace.latency_ms} ms</span>
              </div>

              <div className="trace-item">
                <span className="trace-label">Motor</span>
                <span className="trace-value">
                  <span
                    className={`pill ${trace.llm_mode === "bedrock" ? "pill-ok" : "pill-warn"}`}
                  >
                    {trace.llm_mode}
                  </span>
                </span>
              </div>

              <div className="trace-item">
                <span className="trace-label">Hilo</span>
                <span className="trace-value trace-mono">{trace.thread_id}</span>
              </div>

              <div className="trace-item">
                <span className="trace-label">Negocio en memoria</span>
                <span className="trace-value">
                  {business
                    ? `${business.citas} citas · ${business.pedidos} pedidos`
                    : "sin datos todavía"}
                </span>
              </div>
            </div>
          )}
        </div>
      </section>

      {llmMode === "fake" ? (
        <div className="notice-banner warning-banner" style={{ marginTop: 14 }}>
          <strong>Simulador.</strong>
          <span>
            El prompt se envía al grafo, pero las respuestas son deterministas. Para
            evaluar el prompt de verdad, arranca la API con credenciales de AWS.
          </span>
        </div>
      ) : null}
    </aside>
  );
}
