import { useEffect, useMemo, useState } from "react";

import { api } from "../api";
import { errorMessage } from "../errors";
import type { Health, Tenant } from "../types";
import ChatPanel from "./ChatPanel";
import PromptEditor from "./PromptEditor";
import TenantConfigForm from "./TenantConfigForm";
import TenantSidebar, { type Tab } from "./TenantSidebar";

const TENANT_KEY = "chatbot-console:tenant";
const TAB_KEY = "chatbot-console:tab";

function remember(key: string, value: string | null): void {
  try {
    if (value) {
      window.localStorage.setItem(key, value);
    } else {
      window.localStorage.removeItem(key);
    }
  } catch {
    // localStorage puede estar bloqueado; la consola sigue funcionando.
  }
}

function initialTenant(): string | null {
  try {
    return window.localStorage.getItem(TENANT_KEY);
  } catch {
    return null;
  }
}

function initialTab(): Tab {
  try {
    const guardado = window.localStorage.getItem(TAB_KEY);
    if (guardado === "chat" || guardado === "config" || guardado === "prompts") {
      return guardado;
    }
  } catch {
    // Sin storage: chat por defecto.
  }
  return "chat";
}

export default function ConsoleApp() {
  const [health, setHealth] = useState<Health | null>(null);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(initialTenant);
  const [tab, setTab] = useState<Tab>(initialTab);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void Promise.all([api.health(), api.tenants()])
      .then(([salud, lista]) => {
        if (cancelled) {
          return;
        }
        setHealth(salud);
        setTenants(lista);
        setSelectedId((prev) =>
          lista.some((tenant) => tenant.tenant_id === prev)
            ? prev
            : (lista[0]?.tenant_id ?? null),
        );
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
  }, [reloadKey]);

  useEffect(() => {
    remember(TENANT_KEY, selectedId);
  }, [selectedId]);

  useEffect(() => {
    remember(TAB_KEY, tab);
  }, [tab]);

  const tenant = useMemo(
    () => tenants.find((item) => item.tenant_id === selectedId) ?? null,
    [tenants, selectedId],
  );

  function handleTenantUpdated(updated: Tenant): void {
    setTenants((prev) =>
      prev.map((item) =>
        item.tenant_id === updated.tenant_id ? updated : item,
      ),
    );
  }

  const title =
    tab === "chat"
      ? "Chat simulado"
      : tab === "config"
        ? "Configuración del comercio"
        : "Prompts editables";

  return (
    <div className="console-shell">
      <TenantSidebar
        tenants={tenants}
        selectedId={selectedId}
        onSelect={setSelectedId}
        tab={tab}
        onTab={setTab}
        health={health}
      />

      <main className="main">
        <header className="topbar">
          <div>
            <h1 className="topbar-title">{title}</h1>
            <p className="topbar-sub">
              {tenant
                ? `${tenant.display_name} · ${tenant.tenant_id}`
                : "Consola local de operación"}
            </p>
          </div>
          <div className="badges">
            <span className="badge badge-local">LOCAL</span>
            {health ? (
              <span
                className={`badge ${health.llm_mode === "bedrock" ? "badge-bedrock" : "badge-fake"}`}
                title={health.llm_warning || "Motor de lenguaje efectivo"}
              >
                {health.llm_mode === "bedrock" ? "Bedrock real" : "Simulador"}
              </span>
            ) : null}
            {tenant ? (
              <span className="badge">
                {tenant.allowed_bots.length} bots activos
              </span>
            ) : null}
          </div>
        </header>

        <section className="content">
          {health?.llm_mode === "fake" ? (
            <div className="notice-banner warning-banner">
              <strong>Modo simulador.</strong>
              <span>
                {health.llm_warning ||
                  "Las respuestas no reflejan el prompt. Define CHATBOT_BEDROCK_MODEL_ID y credenciales de AWS para usar el modelo real."}
              </span>
            </div>
          ) : null}

          {error ? (
            <div className="error-banner">
              <strong>No se pudo cargar la consola.</strong>
              <span>{error}</span>
              <button className="btn btn-sm" onClick={() => setReloadKey((n) => n + 1)}>
                Reintentar
              </button>
            </div>
          ) : null}

          {loading ? (
            <div className="empty">
              <div className="spinner" />
              <span>Cargando comercios…</span>
            </div>
          ) : !tenant ? (
            <div className="empty">
              <div className="empty-icon">◇</div>
              <strong>No hay comercios configurados.</strong>
              <span className="small">
                Revisa `console-data/tenants.json` o borra el fichero para sembrar el
                comercio demo.
              </span>
            </div>
          ) : tab === "chat" ? (
            <ChatPanel key={tenant.tenant_id} tenant={tenant} health={health} />
          ) : tab === "config" ? (
            <TenantConfigForm
              key={tenant.tenant_id}
              tenant={tenant}
              onUpdated={handleTenantUpdated}
            />
          ) : (
            <PromptEditor key={tenant.tenant_id} tenant={tenant} />
          )}
        </section>
      </main>
    </div>
  );
}
