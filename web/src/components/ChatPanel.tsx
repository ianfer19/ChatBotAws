import { useEffect, useRef, useState } from "react";

import { api } from "../api";
import { errorMessage } from "../errors";
import type { ChatTrace, Health, StateResponse, Tenant } from "../types";
import TracePanel from "./TracePanel";

interface Props {
  tenant: Tenant;
  health: Health | null;
}

type UiRole = "user" | "assistant" | "notice";

interface UiMessage {
  id: string;
  role: UiRole;
  text: string;
  meta?: string;
}

function makeId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `s-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function customerKey(tenantId: string): string {
  return `chatbot-console:customer:${tenantId}`;
}

function initialCustomer(tenantId: string): string {
  try {
    return window.localStorage.getItem(customerKey(tenantId)) ?? "57300111111";
  } catch {
    return "57300111111";
  }
}

export default function ChatPanel({ tenant, health }: Props) {
  const [messages, setMessages] = useState<UiMessage[]>(() => [
    {
      id: makeId(),
      role: "assistant",
      text: `Hola, soy el asistente de ${tenant.display_name}. Escribe un mensaje para probar el flujo real de la consola.`,
      meta: "mensaje inicial",
    },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [sessionId] = useState(() => makeId());
  const [customerId, setCustomerId] = useState(() => initialCustomer(tenant.tenant_id));
  const [trace, setTrace] = useState<ChatTrace | null>(null);
  const [business, setBusiness] = useState<StateResponse | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, sending]);

  useEffect(() => {
    try {
      window.localStorage.setItem(customerKey(tenant.tenant_id), customerId);
    } catch {
      // Sin storage: el valor vive solo en esta sesión del navegador.
    }
  }, [tenant.tenant_id, customerId]);

  async function refreshBusiness(): Promise<void> {
    try {
      setBusiness(await api.state(tenant.tenant_id));
    } catch {
      setBusiness(null);
    }
  }

  async function send(): Promise<void> {
    const text = input.trim();
    if (!text || sending) {
      return;
    }
    setInput("");
    setMessages((prev) => [
      ...prev,
      { id: makeId(), role: "user", text },
    ]);
    setSending(true);
    try {
      const respuesta = await api.chat({
        tenant_id: tenant.tenant_id,
        session_id: sessionId,
        message: text,
        customer_id: customerId,
      });
      setTrace(respuesta);
      const texto =
        respuesta.reply ??
        respuesta.notice ??
        "El turno terminó sin respuesta del especialista.";
      setMessages((prev) => [
        ...prev,
        {
          id: makeId(),
          role: respuesta.reply ? "assistant" : "notice",
          text: texto,
          meta:
            respuesta.intent !== null
              ? `${respuesta.intent}${respuesta.target ? ` → ${respuesta.target}` : ""} · ${respuesta.latency_ms} ms`
              : `${respuesta.latency_ms} ms`,
        },
      ]);
      await refreshBusiness();
    } catch (exc) {
      setMessages((prev) => [
        ...prev,
        {
          id: makeId(),
          role: "notice",
          text: errorMessage(exc),
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  async function reset(): Promise<void> {
    if (sending) {
      return;
    }
    try {
      await api.resetChat(tenant.tenant_id, sessionId);
      setMessages([
        {
          id: makeId(),
          role: "assistant",
          text: `Conversación reiniciada. Hola de nuevo desde ${tenant.display_name}.`,
          meta: "sesión nueva",
        },
      ]);
      setTrace(null);
      setBusiness(null);
    } catch (exc) {
      setMessages((prev) => [
        ...prev,
        { id: makeId(), role: "notice", text: errorMessage(exc) },
      ]);
    }
  }

  const initials = tenant.display_name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");

  return (
    <div className="chat-layout">
      <div className="chat-column">
        <section className="panel chat-panel">
          <header className="chat-header">
            <div className="chat-header-left">
              <div className="avatar">{initials || "AI"}</div>
              <div>
                <p className="chat-title">Asistente de {tenant.display_name}</p>
                <p className="chat-sub">
                  WhatsApp simulado · sesión {sessionId.slice(0, 8)}
                  {health?.llm_mode === "fake" ? " · simulador" : " · Bedrock"}
                </p>
              </div>
            </div>
            <div className="chat-header-left">
              <label className="sr-only" htmlFor="customer-id">
                Cliente simulado
              </label>
              <input
                id="customer-id"
                className="chat-customer-input"
                value={customerId}
                onChange={(event) => setCustomerId(event.target.value)}
                placeholder="Cliente"
              />
              <button className="btn btn-sm" onClick={() => void reset()}>
                Reset
              </button>
            </div>
          </header>

          <div className="chat-scroll">
            {messages.map((message) => (
              <div key={message.id} className={`message-row ${message.role}`}>
                <div className={`bubble ${message.role}`}>{message.text}</div>
                {message.meta ? (
                  <span className="message-meta">{message.meta}</span>
                ) : null}
              </div>
            ))}
            {sending ? (
              <div className="message-row assistant">
                <div className="typing" aria-label="El asistente está respondiendo">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            ) : null}
            <div ref={endRef} />
          </div>

          <div className="composer">
            <textarea
              rows={1}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void send();
                }
              }}
              placeholder="Escribe como si fueras el cliente…"
              aria-label="Mensaje para el chatbot"
            />
            <div className="composer-actions">
              <span className="composer-hint">
                Enter envía · Shift+Enter salta línea
              </span>
              <button
                className="btn btn-primary"
                onClick={() => void send()}
                disabled={sending || input.trim().length === 0}
              >
                {sending ? <span className="spinner" /> : null}
                Enviar
              </button>
            </div>
          </div>
        </section>
      </div>

      <TracePanel trace={trace} business={business} llmMode={health?.llm_mode ?? null} />
    </div>
  );
}
