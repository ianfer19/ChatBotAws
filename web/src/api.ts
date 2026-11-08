import type {
  ChatTrace,
  Health,
  PromptInfo,
  PromptKind,
  PromptView,
  StateResponse,
  Tenant,
  TenantUpdate,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let code = `http_${response.status}`;
    let message = `La petición falló (${response.status}).`;
    try {
      const body = (await response.json()) as { error?: string; message?: string };
      code = body.error ?? code;
      message = body.message ?? message;
    } catch {
      // Respuesta no JSON: se conserva el mensaje genérico.
    }
    throw new ApiError(code, message, response.status);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<Health>("/api/health"),

  tenants: () => request<Tenant[]>("/api/tenants"),

  tenant: (tenantId: string) =>
    request<Tenant>(`/api/tenants/${encodeURIComponent(tenantId)}`),

  updateTenant: (tenantId: string, update: TenantUpdate) =>
    request<Tenant>(`/api/tenants/${encodeURIComponent(tenantId)}`, {
      method: "PUT",
      body: JSON.stringify(update),
    }),

  prompts: (tenantId: string) =>
    request<PromptInfo[]>(`/api/tenants/${encodeURIComponent(tenantId)}/prompts`),

  prompt: (tenantId: string, kind: PromptKind) =>
    request<PromptView>(
      `/api/tenants/${encodeURIComponent(tenantId)}/prompts/${kind}`,
    ),

  updatePrompt: (tenantId: string, kind: PromptKind, content: string) =>
    request<PromptView>(
      `/api/tenants/${encodeURIComponent(tenantId)}/prompts/${kind}`,
      { method: "PUT", body: JSON.stringify({ content }) },
    ),

  resetPrompt: (tenantId: string, kind: PromptKind) =>
    request<PromptView>(
      `/api/tenants/${encodeURIComponent(tenantId)}/prompts/${kind}`,
      { method: "DELETE" },
    ),

  chat: (input: {
    tenant_id: string;
    session_id: string;
    message: string;
    customer_id: string;
  }) =>
    request<ChatTrace>("/api/chat", {
      method: "POST",
      body: JSON.stringify(input),
    }),

  resetChat: (tenantId: string, sessionId: string) =>
    request<{ ok: boolean }>("/api/chat/reset", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId, session_id: sessionId }),
    }),

  state: (tenantId: string) =>
    request<StateResponse>(`/api/tenants/${encodeURIComponent(tenantId)}/state`),
};
