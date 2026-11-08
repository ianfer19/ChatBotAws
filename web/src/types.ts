export type BotName = "sales" | "appointments" | "orders" | "faq";
export type PromptKind = "supervisor" | "appointments" | "orders" | "faq";

export interface Health {
  status: string;
  environment: string;
  llm_mode: string;
  llm_warning: string;
}

export interface Tenant {
  tenant_id: string;
  display_name: string;
  tone: string;
  language: string;
  allowed_bots: BotName[];
  model_id: string | null;
}

export interface TenantUpdate {
  display_name?: string;
  tone?: string;
  language?: string;
  allowed_bots?: BotName[];
  model_id?: string | null;
}

export interface PromptInfo {
  kind: PromptKind;
  is_override: boolean;
  length: number;
}

export interface PromptView {
  kind: PromptKind;
  content: string;
  is_override: boolean;
  base_content: string;
}

export interface ChatTrace {
  reply: string | null;
  intent: string | null;
  confidence: number | null;
  target: string | null;
  route_error: string | null;
  pending_outcome: string | null;
  notice: string | null;
  latency_ms: number;
  thread_id: string;
  llm_mode: string;
  llm_warning: string;
}

export interface StateResponse {
  citas: number;
  pedidos: number;
}

export interface ApiErrorBody {
  error: string;
  message: string;
}
