import type { Health, Tenant } from "../types";

export type Tab = "chat" | "config" | "prompts";

interface Props {
  tenants: Tenant[];
  selectedId: string | null;
  onSelect: (tenantId: string) => void;
  tab: Tab;
  onTab: (tab: Tab) => void;
  health: Health | null;
}

const TABS: Array<{ id: Tab; label: string; icon: string }> = [
  { id: "chat", label: "Chat simulado", icon: "◌" },
  { id: "config", label: "Comercio", icon: "⚙" },
  { id: "prompts", label: "Prompts", icon: "✎" },
];

export default function TenantSidebar({
  tenants,
  selectedId,
  onSelect,
  tab,
  onTab,
  health,
}: Props) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">CB</div>
        <div>
          <p className="brand-title">ChatBotAws</p>
          <p className="brand-sub">Consola local · Fase A</p>
        </div>
      </div>

      <div className="sidebar-section">
        <p className="sidebar-label">Comercios</p>
        <div className="tenant-list">
          {tenants.length === 0 ? (
            <span className="tenant-meta">Sin comercios</span>
          ) : (
            tenants.map((tenant) => (
              <button
                key={tenant.tenant_id}
                className={`tenant-button ${tenant.tenant_id === selectedId ? "active" : ""}`}
                onClick={() => onSelect(tenant.tenant_id)}
              >
                <span className="tenant-name">{tenant.display_name}</span>
                <span className="tenant-meta">{tenant.tenant_id}</span>
              </button>
            ))
          )}
        </div>
      </div>

      <div className="sidebar-section">
        <p className="sidebar-label">Secciones</p>
        <nav className="nav-tabs">
          {TABS.map((item) => (
            <button
              key={item.id}
              className={`nav-tab ${tab === item.id ? "active" : ""}`}
              onClick={() => onTab(item.id)}
            >
              <span className="nav-icon">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>
      </div>

      <div className="sidebar-footer">
        <span>
          Motor:{" "}
          <strong>{health?.llm_mode === "bedrock" ? "Bedrock" : "Simulador"}</strong>
        </span>
        <span>API: http://127.0.0.1:8000</span>
        <span>Sin autenticación · solo localhost</span>
      </div>
    </aside>
  );
}
