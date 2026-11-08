import { useEffect, useState } from "react";

import { api } from "../api";
import { errorMessage } from "../errors";
import type { BotName, Tenant, TenantUpdate } from "../types";

interface Props {
  tenant: Tenant;
  onUpdated: (tenant: Tenant) => void;
}

const BOTS: Array<{ id: BotName; label: string; hint: string }> = [
  { id: "sales", label: "Ventas", hint: "Catálogo y consultas comerciales" },
  { id: "appointments", label: "Citas", hint: "Disponibilidad y reservas" },
  { id: "orders", label: "Pedidos", hint: "Carrito, estado y confirmación" },
  { id: "faq", label: "FAQ", hint: "Conocimiento y preguntas frecuentes" },
];

export default function TenantConfigForm({ tenant, onUpdated }: Props) {
  const [displayName, setDisplayName] = useState(tenant.display_name);
  const [tone, setTone] = useState(tenant.tone);
  const [language, setLanguage] = useState(tenant.language);
  const [modelId, setModelId] = useState(tenant.model_id ?? "");
  const [allowedBots, setAllowedBots] = useState<BotName[]>(tenant.allowed_bots);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDisplayName(tenant.display_name);
    setTone(tenant.tone);
    setLanguage(tenant.language);
    setModelId(tenant.model_id ?? "");
    setAllowedBots(tenant.allowed_bots);
    setError(null);
  }, [tenant]);

  function toggleBot(bot: BotName): void {
    setAllowedBots((prev) =>
      prev.includes(bot) ? prev.filter((item) => item !== bot) : [...prev, bot],
    );
  }

  async function save(): Promise<void> {
    setSaving(true);
    setMessage(null);
    setError(null);
    const update: TenantUpdate = {
      display_name: displayName.trim(),
      tone: tone.trim(),
      language,
      allowed_bots: allowedBots,
      model_id: modelId.trim() ? modelId.trim() : null,
    };
    try {
      const actualizado = await api.updateTenant(tenant.tenant_id, update);
      onUpdated(actualizado);
      setMessage("Perfil guardado. El grafo se recompila en el siguiente mensaje.");
    } catch (exc) {
      setError(errorMessage(exc));
    } finally {
      setSaving(false);
    }
  }

  function discard(): void {
    setDisplayName(tenant.display_name);
    setTone(tenant.tone);
    setLanguage(tenant.language);
    setModelId(tenant.model_id ?? "");
    setAllowedBots(tenant.allowed_bots);
    setMessage(null);
    setError(null);
  }

  return (
    <section className="panel">
      <header className="panel-header">
        <div>
          <h2 className="panel-title">Perfil del comercio</h2>
          <p className="panel-sub">
            Nombre, tono y bots activos. Los prompts se editan en su propia sección.
          </p>
        </div>
        <span className="badge">{tenant.tenant_id}</span>
      </header>

      <div className="panel-body">
        {message ? <div className="success-banner">{message}</div> : null}
        {error ? <div className="error-banner">{error}</div> : null}

        <form
          className="form"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <div className="form-grid">
            <div className="field">
              <label htmlFor="display-name">Nombre comercial</label>
              <input
                id="display-name"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                maxLength={120}
                required
              />
              <span className="field-hint">
                Es el nombre que usa el saludo y la cabecera del chat.
              </span>
            </div>

            <div className="field">
              <label htmlFor="tone">Tono</label>
              <input
                id="tone"
                value={tone}
                onChange={(event) => setTone(event.target.value)}
                maxLength={120}
                placeholder="cercano, formal, divertido…"
              />
              <span className="field-hint">
                Orientativo para el prompt; no es una regla de negocio.
              </span>
            </div>

            <div className="field">
              <label htmlFor="language">Idioma</label>
              <select
                id="language"
                value={language}
                onChange={(event) => setLanguage(event.target.value)}
              >
                <option value="es">Español</option>
                <option value="en">English</option>
              </select>
            </div>

            <div className="field">
              <label htmlFor="model-id">Modelo de Bedrock</label>
              <input
                id="model-id"
                value={modelId}
                onChange={(event) => setModelId(event.target.value)}
                placeholder="Usa el del entorno si se deja vacío"
              />
              <span className="field-hint">
                Solo aplica en modo Bedrock real; el simulador lo ignora.
              </span>
            </div>
          </div>

          <div className="field">
            <label>Bots activos</label>
            <div className="checkbox-grid">
              {BOTS.map((bot) => (
                <label key={bot.id} className="checkbox">
                  <input
                    type="checkbox"
                    checked={allowedBots.includes(bot.id)}
                    onChange={() => toggleBot(bot.id)}
                  />
                  <span>
                    <strong>{bot.label}</strong>
                    <span className="field-hint" style={{ display: "block" }}>
                      {bot.hint}
                    </span>
                  </span>
                </label>
              ))}
            </div>
            <span className="field-hint">
              El supervisor y el saludo siempre están activos. Ventas aún no tiene
              especialista en la Fase A; desactivarlo no rompe nada.
            </span>
          </div>

          <div className="form-actions">
            <button className="btn btn-primary" type="submit" disabled={saving}>
              {saving ? <span className="spinner" /> : null}
              Guardar perfil
            </button>
            <button
              className="btn"
              type="button"
              onClick={discard}
              disabled={saving}
            >
              Descartar cambios
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}
