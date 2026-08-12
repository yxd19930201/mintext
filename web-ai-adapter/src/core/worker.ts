import { performance } from "node:perf_hooks";
import fs from "node:fs/promises";
import path from "node:path";
import type {
  GenerateRequest,
  GenerateResponse,
  ProviderStatus,
  ResolvedExecutionMode,
} from "../contracts.js";
import { normalizeError } from "./errors.js";
import { parseAndValidateJson } from "./json-envelope.js";
import { buildPrompt } from "./prompt.js";
import { resolveExecutionMode } from "./mode-router.js";

export interface WorkerAdapter {
  readonly id: string;
  readonly definition: {
    label: string;
    homeUrl: string;
  };
  generate(prompt: string, timeoutMs: number, mode?: ResolvedExecutionMode): Promise<{
    rawText: string;
    conversationId: string | null;
    recovered?: boolean;
    salvagedAfterTimeout?: boolean;
  }>;
  cleanupCurrentConversation(): Promise<void>;
  /** Remember an answer that failed validation so recovery will not loop on it. */
  markRejectedRecovery?(rawText: string): void;
  warmup?(): Promise<void>;
  close(): Promise<void>;
  disconnect?(): Promise<void>;
}

export class ChannelWorker {
  private tail: Promise<void> = Promise.resolve();
  private queued = 0;
  private running = false;
  private paused = false;

  constructor(
    private readonly adapter: WorkerAdapter,
    private readonly defaultTimeoutMs: number,
  ) {}

  status(): ProviderStatus {
    return {
      id: this.adapter.id,
      label: this.adapter.definition.label,
      homeUrl: this.adapter.definition.homeUrl,
      queued: this.queued,
      running: this.running,
      paused: this.paused,
      enabled: true,
    };
  }

  enqueue(request: GenerateRequest): Promise<GenerateResponse> {
    return this.runExclusive(() => this.run(request));
  }

  runExclusive<T>(operation: () => Promise<T>, allowPaused = false): Promise<T> {
    if (this.paused && !allowPaused) {
      return Promise.reject(new Error(`${this.adapter.definition.label} 渠道已暂停`));
    }
    this.queued += 1;
    const task = this.tail.then(async () => {
      this.queued -= 1;
      if (this.paused && !allowPaused) {
        throw new Error(`${this.adapter.definition.label} 渠道已暂停`);
      }
      this.running = true;
      try {
        return await operation();
      } finally {
        this.running = false;
      }
    });
    this.tail = task.then(
      () => undefined,
      () => undefined,
    );
    return task;
  }

  async pause(): Promise<void> {
    this.paused = true;
    await this.runExclusive(() => this.adapter.close(), true);
  }

  async resume(): Promise<void> {
    this.paused = false;
    await this.runExclusive(async () => undefined, true);
  }

  isPaused(): boolean {
    return this.paused;
  }

  async close(): Promise<void> {
    await this.tail;
    if (this.adapter.disconnect) await this.adapter.disconnect();
    else await this.adapter.close();
  }

  async warmup(): Promise<void> {
    await this.adapter.warmup?.();
  }

  private async run(request: GenerateRequest): Promise<GenerateResponse> {
    const queuedAt = new Date().toISOString();
    const startedAt = new Date().toISOString();
    const started = performance.now();
    let conversationId: string | null = null;
    let rawText: string | undefined;

    const mode = resolveExecutionMode(request);
    const maxAttempts = Math.min(3, Math.max(1, request.maxAttempts ?? 2));
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
        try {
          const prompt = buildPrompt(request);
          const result = await this.adapter.generate(
            prompt,
            request.timeoutMs ?? this.defaultTimeoutMs,
            mode,
          );
          conversationId = result.conversationId;
          rawText = result.rawText;
          let data: unknown;
          try {
            data = parseAndValidateJson(result.rawText, request.outputSchema);
          } catch (parseError) {
            // Recovered/salvaged text may still fail schema. Mark it rejected so
            // the next attempt re-submits instead of reusing the same bad page.
            if (result.recovered || result.salvagedAfterTimeout) {
              this.adapter.markRejectedRecovery?.(result.rawText);
            }
            throw parseError;
          }
          if ((request.cleanup ?? "none") === "after_success") {
            await this.adapter.cleanupCurrentConversation().catch(() => undefined);
          }
          return {
            requestId: request.requestId,
            success: true,
            provider: request.provider,
            conversationId,
            data,
            meta: {
              queuedAt,
              startedAt,
              finishedAt: new Date().toISOString(),
              durationMs: Math.round(performance.now() - started),
              attempt,
              mode,
              recovered: Boolean(result.recovered),
              salvagedAfterTimeout: Boolean(result.salvagedAfterTimeout),
            },
            error: null,
          };
        } catch (caught) {
          const error = normalizeError(caught);
          const response: GenerateResponse = {
            requestId: request.requestId,
            success: false,
            provider: request.provider,
            conversationId,
            data: null,
            rawText,
            meta: {
              queuedAt,
              startedAt,
              finishedAt: new Date().toISOString(),
              durationMs: Math.round(performance.now() - started),
              attempt,
              mode,
            },
            error: {
              code: error.code,
              message: error.message,
              retryable: error.retryable,
              details: error.details,
            },
          };
          if (!error.retryable || attempt >= maxAttempts) {
            await this.persistFailureDiagnostic(request, response).catch(() => undefined);
            return response;
          }
          // Keep the browser conversation: the next attempt first checks whether
          // the previous thinking timeout left a correct answer on the page.
          await new Promise((resolve) => setTimeout(resolve, 250 * attempt));
        }
    }
    throw new Error("请求重试状态异常");
  }

  private async persistFailureDiagnostic(request: GenerateRequest, response: GenerateResponse): Promise<void> {
    const root = path.resolve(process.env.WEB_AI_DIAGNOSTICS_ROOT ?? ".runtime/diagnostics");
    await fs.mkdir(root, { recursive: true });
    const safeRequest = request.requestId.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 80);
    const filename = `${request.provider}-${safeRequest}-${Date.now()}.json`;
    await fs.writeFile(path.join(root, filename), JSON.stringify({
      requestId: request.requestId,
      jobId: request.jobId,
      taskType: request.taskType,
      provider: request.provider,
      outputSchema: request.outputSchema,
      response,
    }), "utf8");
  }
}
