export type User = { id: string; email: string; role: string; available: boolean };
export type Config = Record<string, unknown>;
export type FlowNode = {
  id: string;
  type: string;
  config: Config;
  position: { x: number; y: number };
};
export type FlowEdge = { id: string; source: string; target: string; label: string };
export type Flow = { schema_version: number; entry: string; nodes: FlowNode[]; edges: FlowEdge[] };
export type Bot = {
  project_id: string | null;
  description: string;
  purpose: string;
  id: string;
  name: string;
  origins: string[];
  draft: Flow;
  published_id: string | null;
};
export type Provider = {
  id: string;
  name: string;
  kind: string;
  model: string;
  purpose: string;
  capabilities: Record<string, boolean>;
};
export type Tool = { id: string; name: string; description: string };
export type Collection = {
  id: string;
  name: string;
  bot_id: string;
  provider_id: string;
  generation: number;
};
export type Queue = { id: string; name: string };
export type Message = {
  id: string;
  role: string;
  content: string;
  sources: { name: string; chunk: number }[];
  created: number;
};
export type Conversation = {
  id: string;
  bot_id: string;
  version_id: string;
  status: string;
  agent_id: string | null;
  queue_id: string | null;
  created: number;
  queued_at: number | null;
  messages?: Message[];
};
export type Trace = {
  id: string;
  node_id: string;
  status: string;
  detail: {
    code?: string;
    route?: { target_type: string; target_id: string; version_id: string; name?: string } | null;
    usage?: { input_tokens: number; output_tokens: number; latency_ms: number }[];
  };
  created: number;
};

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData))
    headers.set('Content-Type', 'application/json');
  const r = await fetch('/api/v1' + path, { ...init, headers, credentials: 'same-origin' });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    const detail = body.detail;
    throw new Error(
      typeof detail === 'string'
        ? detail
        : detail
          ? JSON.stringify(detail)
          : `Request failed (${r.status})`,
    );
  }
  return r.json();
}
export const post = <T = unknown>(path: string, body?: unknown) =>
  api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });
export const put = <T = unknown>(path: string, body: unknown) =>
  api<T>(path, { method: 'PUT', body: JSON.stringify(body) });
export function download(name: string, value: unknown) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }),
  );
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export type Orchestrator = {
  provider_id: string | null;
  description: string;
  purpose: string;
  instructions?: string;
  welcome?: string;
  flow_ids: string[];
  agent_ids: string[];
  fallback_queue_id?: string | null;
};
export type Project = {
  id: string;
  name: string;
  description: string;
  purpose: string;
  origins: string[];
  orchestrator: Orchestrator;
  published_id: string | null;
};
export type AgentDefinition = {
  provider_id: string | null;
  instructions: string;
  tool_ids: string[];
  collection_ids: string[];
  max_iterations: number;
  output_schema?: Record<string, unknown> | null;
};
export type FullAgent = {
  id: string;
  project_id: string;
  name: string;
  description: string;
  purpose: string;
  draft: AgentDefinition;
  published_id: string | null;
};
export type TestSession = { conversation_id: string; token: string };
