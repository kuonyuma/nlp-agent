export type TurnStatus =
  | "accepted"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted";

export interface AuthSession {
  user_id: string;
  workspace_ids: string[];
  roles: string[];
  csrf_token: string;
  expires_at: number;
}

export interface DeveloperSnapshot {
  runtime: Record<string, unknown>;
  features: Record<string, { available: boolean; reason: string }>;
  models: {
    defaults: Record<string, unknown>;
    routes: Record<string, unknown>;
    models: Record<string, Record<string, unknown>>;
    presets: Record<string, Record<string, unknown>>;
    providers: Record<string, Record<string, unknown>>;
  };
  tools: {
    catalog_revision: number;
    items: Array<Record<string, unknown>>;
    policies: Record<string, unknown>;
    mcp_servers: Record<string, Record<string, unknown>>;
    custom: Record<string, unknown>;
  };
  skills: Array<{ name: string; path: string; format: string; bytes: number; modified_at: number }>;
  agents: Record<string, unknown>;
  workspace: { roots: Array<{ name: string; path: string; exists: boolean; writable: boolean }> };
  web: Record<string, unknown>;
}

export interface SessionSummary {
  session_id: string;
  user_id: string;
  workspace_id: string;
  channel: string;
  created_at?: number;
  last_active?: number;
}

export interface TurnRecord {
  turn_id: string;
  session_id: string;
  status: TurnStatus;
  input_text: string;
  final_text: string | null;
  error_kind: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface ServerEvent {
  v: "1";
  type: string;
  request_id?: string;
  event_id?: string;
  session_id?: string;
  turn_id?: string;
  sequence?: number;
  timestamp: string;
  payload: Record<string, unknown>;
}

export interface LearningContext {
  topic: string;
  level: "beginner" | "intermediate" | "advanced";
  mode: "explain" | "socratic" | "practice" | "review";
}

export interface ActivityItem {
  id: string;
  kind: "thinking" | "tool" | "worker" | "recovery";
  label: string;
  status: "running" | "completed" | "error";
  detail?: string;
}

export interface ChatMessage {
  id: string;
  turnId: string;
  role: "user" | "assistant";
  content: string;
  reasoning?: string;
  status?: TurnStatus;
  activities?: ActivityItem[];
  createdAt: string;
}

export interface SessionLearningMeta {
  title?: string;
  topic?: string;
  favorite?: boolean;
  archived?: boolean;
  summary?: string;
  concepts?: string[];
  reviewConcepts?: string[];
  updatedAt?: number;
}

export interface LearningPreferences {
  version: 1;
  context: LearningContext;
  sessions: Record<string, SessionLearningMeta>;
}

export interface UserSettings {
  locale: string;
  theme: "system" | "light" | "dark";
  show_reasoning: boolean;
  stream_render_interval_ms: number;
}
