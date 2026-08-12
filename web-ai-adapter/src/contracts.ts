export const providerIds = ["deepseek", "chatgpt"] as const;

export type ProviderId = (typeof providerIds)[number] | (string & {});
export type CleanupMode = "none" | "after_success";
export type ExecutionMode = "auto" | "fast" | "quality" | "current";
export type ResolvedExecutionMode = Exclude<ExecutionMode, "auto">;
export type TaskType =
  | "novel_design"
  | "outline"
  | "chapter_draft"
  | "chapter_rewrite"
  | "continuity_review"
  | "quality_review"
  | "summary"
  | "state_extract"
  | "metadata"
  | "json_transform"
  | "custom";

export interface JsonSchema {
  [key: string]: unknown;
}

export interface GenerateRequest {
  requestId: string;
  /** Optional backend workflow id. It becomes the durable idempotency key. */
  jobId?: string;
  idempotencyKey?: string;
  provider: ProviderId;
  input: unknown;
  taskType?: TaskType;
  instruction?: string;
  outputSchema?: JsonSchema;
  mode?: ExecutionMode;
  cleanup?: CleanupMode;
  timeoutMs?: number;
  maxAttempts?: number;
  /** snake_case aliases accepted from the FastAPI backend contract */
  request_id?: string;
  job_id?: string;
  idempotency_key?: string;
  task_type?: TaskType;
  prompt?: string;
  json_schema?: JsonSchema;
  timeout_ms?: number;
  max_attempts?: number;
}

export interface GenerateMeta {
  queuedAt: string;
  startedAt: string;
  finishedAt: string;
  durationMs: number;
  attempt: number;
  mode: ResolvedExecutionMode;
  cached?: boolean;
  /** Answer was reused from the existing page conversation for the same prompt. */
  recovered?: boolean;
  /** Answer was harvested after a thinking/generation wait timeout. */
  salvagedAfterTimeout?: boolean;
}

export interface AdapterErrorBody {
  code: string;
  message: string;
  retryable: boolean;
  details?: unknown;
}

export interface GenerateResponse<T = unknown> {
  requestId: string;
  success: boolean;
  provider: ProviderId;
  conversationId: string | null;
  data: T | null;
  rawText?: string;
  meta: GenerateMeta;
  error: AdapterErrorBody | null;
}

export interface BatchRequest {
  requests: GenerateRequest[];
}

export interface ProviderStatus {
  id: ProviderId;
  label: string;
  homeUrl: string;
  queued: number;
  running: boolean;
  enabled: boolean;
  state?: "starting" | "login_required" | "verification_required" | "ready" | "busy" | "paused" | "error";
  ready?: boolean;
  reason?: string;
  checkedAt?: string;
  paused?: boolean;
  authenticated?: boolean;
  lastError?: string;
}

export interface ProviderCapabilities {
  id: ProviderId;
  enabled: boolean;
  structuredJson: true;
  independentConversation: true;
  modes: ResolvedExecutionMode[];
  persistentIdempotency: true;
  maxPayloadBytes: number;
}
