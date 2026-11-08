import { useEffect, useState } from "react";

import { api } from "../api";
import { errorMessage } from "../errors";
import type { PromptInfo, PromptKind, PromptView, Tenant } from "../types";

interface Props {
  tenant: Tenant;
}

const KIND_LABELS: Record<PromptKind, string> = {
  supervisor: "Supervisor",
  appointments: "Citas",
  orders: "Pedidos",
  faq: "FAQ",
};

const KIND_HINTS: Record<PromptKind, string> = {
  supervisor: "Clasifica la intención y decide el enrutado.",
  appointments: "Interpreta y redacta turnos de citas.",
  orders: "Interpreta y redacta turnos de pedidos.",
  faq: "Responde solo con evidencia recuperada.",
};

export default function PromptEditor({ tenant }: Props) {
  const [infos, setInfos] = useState<PromptInfo[]>([]);
  const [kind, setKind] = useState<PromptKind>("supervisor");
  const [view, setView] = useState<PromptView | null>(null);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function reloadInfos(): Promise<void> {
    setInfos(await api.prompts(tenant.tenant_id));
  }

  async function loadPrompt(next: PromptKind): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const prompt = await api.prompt(tenant.tenant_id, next);
      setView(prompt);
      setDraft(prompt.content);
      setKind(next);
    } catch (exc) {
      setError(errorMessage(exc));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void Promise.all([
      api.prompts(tenant.tenant_id),
      api.prompt(tenant.tenant_id, "supervisor"),
    ])
      .then(([lista, prompt]) => {
        if (cancelled) {
          return;
        }
        setInfos(lista);
        setView(prompt);
        setDraft(prompt.content);
        setKind("supervisor");
      })
      .catch((exc) => {
        if (!cancelled) {
          setError(errorMessage(exc));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [tenant.tenant_id]);

  async function save(): Promise<void> {
    if (view === null) {
      return;
    }
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const actualizado = await api.updatePrompt(
        tenant.tenant_id,
        kind,
        draft,
      );
      setView(actualizado);
      setDraft(actualizado.content);
      await reloadInfos();
      setMessage("Prompt guardado. Se aplica en el siguiente turno de este comercio.");
    } catch (exc) {
      setError(errorMessage(exc));
    } finally {
      setSaving(false);
    }
  }

  async function restore(): Promise<void> {
    if (
      view === null ||
      !window.confirm(
        "¿Restaurar la plantilla base? Se perderá el override de este comercio.",
      )
    ) {
      return;
    }
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const base = await api.resetPrompt(tenant.tenant_id, kind);
      setView(base);
      setDraft(base.content);
      await reloadInfos();
      setMessage("Override eliminado; se usa la plantilla base.");
    } catch (exc) {
      setError(errorMessage(exc));
    } finally {
      setSaving(false);
    }
  }

  const dirty = view !== null && draft !== view.content;

  return (
    <section className="panel">
      <header className="panel-header">
        <div>
          <h2 className="panel-title">Prompts editables</h2>
          <p className="panel-sub">
            Override por comercio con restauración a la plantilla base de `prompts/base/`.
          </p>
        </div>
        <span className="badge">{tenant.display_name}</span>
      </header>

      <div className="panel-body">
        {message ? <div className="success-banner">{message}</div> : null}
        {error ? <div className="error-banner">{error}</div> : null}

        <div className="notice-banner warning-banner">
          <strong>Regla del repo.</strong>
          <span>
            No pongas precios, stock, horarios ni reglas de negocio en el prompt: esos
            datos salen de tools y del backend. El prompt solo guía tono, redacción y
            clasificación.
          </span>
        </div>

        <div className="prompt-layout">
          <nav className="prompt-tabs" aria-label="Tipos de prompt">
            {infos.map((info) => (
              <button
                key={info.kind}
                className={`prompt-tab ${info.kind === kind ? "active" : ""}`}
                onClick={() => void loadPrompt(info.kind)}
              >
                <span className="prompt-tab-name">{KIND_LABELS[info.kind]}</span>
                <span className="prompt-tab-meta">
                  {info.is_override ? "Override" : "Base"} · {info.length} chars
                </span>
              </button>
            ))}
          </nav>

          {loading || view === null ? (
            <div className="empty">
              <div className="spinner" />
              <span>Cargando prompt…</span>
            </div>
          ) : (
            <div className="prompt-editor">
              <div className="prompt-toolbar">
                <div className="prompt-toolbar-left">
                  <strong>{KIND_LABELS[kind]}</strong>
                  <span
                    className={`pill ${view.is_override ? "pill-warn" : "pill-neutral"}`}
                  >
                    {view.is_override ? "Override del comercio" : "Plantilla base"}
                  </span>
                  <span className="muted small">{KIND_HINTS[kind]}</span>
                </div>
                <div className="prompt-toolbar-left">
                  <button
                    className="btn btn-sm"
                    onClick={() => setDraft(view.base_content)}
                    disabled={saving}
                  >
                    Copiar base
                  </button>
                  <button
                    className="btn btn-sm btn-danger"
                    onClick={() => void restore()}
                    disabled={saving || !view.is_override}
                  >
                    Restaurar base
                  </button>
                </div>
              </div>

              <textarea
                className="prompt-textarea"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                spellCheck={false}
                aria-label={`Prompt de ${KIND_LABELS[kind]}`}
              />

              <div className="prompt-meta">
                <span>
                  {draft.length} caracteres
                  {dirty ? " · cambios sin guardar" : ""}
                </span>
                <span className="prompt-toolbar-left">
                  <button
                    className="btn btn-primary"
                    onClick={() => void save()}
                    disabled={saving || !dirty}
                  >
                    {saving ? <span className="spinner" /> : null}
                    Guardar prompt
                  </button>
                </span>
              </div>

              <details className="base-details">
                <summary>Ver plantilla base (solo lectura)</summary>
                <pre>{view.base_content}</pre>
              </details>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
