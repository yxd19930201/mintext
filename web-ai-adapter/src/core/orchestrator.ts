import path from "node:path";
import type {
  GenerateRequest,
  GenerateResponse,
  ProviderStatus,
} from "../contracts.js";
import { AdapterError } from "./errors.js";
import { ChannelWorker } from "./worker.js";
import { BrowserProviderAdapter } from "../providers/browser-adapter.js";
import type { BrowserChatEvent, BrowserChatModel, BrowserProviderProbe } from "../providers/browser-adapter.js";
import { loadProviderDefinitions } from "../providers/definitions.js";
import { IdempotencyStore } from "./idempotency-store.js";

interface CachedTask {
  fingerprint: string;
  promise: Promise<GenerateResponse>;
}

export class Orchestrator {
  private readonly workers = new Map<string, ChannelWorker>();
  private readonly adapters = new Map<string, BrowserProviderAdapter>();
  private readonly tasks = new Map<string, CachedTask>();
  private readonly loginTasks = new Map<string, Promise<ProviderStatus>>();
  private readonly store: IdempotencyStore;
  private readonly probes = new Map<string, BrowserProviderProbe>();

  constructor() {
    const definitions = loadProviderDefinitions();
    const profileRoot = process.env.WEB_AI_PROFILE_ROOT ?? ".profiles";
    const headless = process.env.WEB_AI_HEADLESS === "true";
    const timeoutMs = Number(process.env.WEB_AI_DEFAULT_TIMEOUT_MS ?? 300_000);
    const enabledProviderIds = new Set(
      (process.env.WEB_AI_ENABLED_PROVIDERS ?? "deepseek,chatgpt")
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean),
    );
    this.store = new IdempotencyStore(
      path.resolve(process.env.WEB_AI_IDEMPOTENCY_ROOT ?? ".runtime/idempotency"),
    );

    for (const definition of Object.values(definitions)) {
      if (!enabledProviderIds.has(definition.id)) continue;
      const adapter = new BrowserProviderAdapter(
        definition,
        path.resolve(profileRoot),
        headless,
      );
      this.workers.set(definition.id, new ChannelWorker(adapter, timeoutMs));
      this.adapters.set(definition.id, adapter);
    }
    if (this.workers.size === 0) {
      throw new Error("WEB_AI_ENABLED_PROVIDERS 没有匹配到任何可用渠道");
    }
  }

  statuses(): ProviderStatus[] {
    return [...this.workers.entries()].map(([provider, worker]) => {
      const status = worker.status();
      const probe = this.probes.get(provider);
      if (worker.isPaused()) {
        return { ...status, state: "paused", ready: false, paused: true,
          reason: "渠道正在等待网页登录完成", checkedAt: probe?.checkedAt };
      }
      if (status.running) return { ...status, state: "busy", ready: true, checkedAt: probe?.checkedAt };
      return {
        ...status,
        state: probe?.state ?? "starting",
        ready: Boolean(probe?.ready),
        reason: probe?.reason,
        checkedAt: probe?.checkedAt,
      };
    });
  }

  async generate(request: GenerateRequest): Promise<GenerateResponse> {
    request = this.normalizeRequest(request);
    this.validateRequest(request);
    const key = this.store.keyFor(request);
    const fingerprint = this.store.fingerprint(request);
    const cached = await this.store.load(request);
    if (cached) return cached;
    const existing = this.tasks.get(key);
    if (existing) {
      if (existing.fingerprint !== fingerprint) {
        throw new AdapterError(
          "REQUEST_ID_CONFLICT",
          `幂等键 ${key} 已用于不同请求`,
          false,
        );
      }
      return existing.promise;
    }

    const worker = this.workers.get(request.provider);
    if (!worker) {
      throw new AdapterError("UNKNOWN_PROVIDER", `未知渠道：${request.provider}`, false);
    }
    const promise = worker.enqueue(request).then(async (response) => {
      if (response.success) {
        await this.store.save(request, response);
        this.markReady(request.provider);
      } else if (response.error) {
        this.recordError(request.provider, new AdapterError(
          response.error.code, response.error.message, response.error.retryable, response.error.details,
        ));
      }
      this.tasks.delete(key);
      return response;
    });
    this.tasks.set(key, { fingerprint, promise });
    if (this.tasks.size > 1_000) {
      const oldest = this.tasks.keys().next().value as string | undefined;
      if (oldest) this.tasks.delete(oldest);
    }
    return promise;
  }

  async lookup(request: GenerateRequest): Promise<{
    status: "completed" | "running" | "missing";
    response?: GenerateResponse;
  }> {
    request = this.normalizeRequest(request);
    this.validateRequest(request);
    const cached = await this.store.load(request);
    if (cached) return { status: "completed", response: cached };
    const key = this.store.keyFor(request);
    const existing = this.tasks.get(key);
    if (!existing) return { status: "missing" };
    const fingerprint = this.store.fingerprint(request);
    if (existing.fingerprint !== fingerprint) {
      throw new AdapterError("REQUEST_ID_CONFLICT", `幂等键 ${key} 已用于不同请求`, false);
    }
    return { status: "running" };
  }

  generateBatch(requests: GenerateRequest[]): Promise<GenerateResponse[]> {
    return Promise.all(requests.map((request) => this.generate(request)));
  }

  async chatModels(): Promise<Array<BrowserChatModel & { provider: string; error?: string }>> {
    const settled = await Promise.all([...this.adapters.entries()].map(async ([provider, adapter]) => {
      try {
        const worker = this.workers.get(provider)!;
        return await worker.runExclusive(async () => {
          const probe = await adapter.probe();
          this.probes.set(provider, probe);
          if (!probe.ready) {
            return [{ id: "unavailable", name: `${provider} 不可用`, available: false, provider,
              error: probe.reason ?? `${provider} 当前不可用` }];
          }
          return (await adapter.detectChatModels()).map((model) => ({ ...model, provider }));
        });
      } catch (error) {
        this.recordError(provider, error);
        return [{ id: "unavailable", name: `${provider} 不可用`, available: false, provider,
          error: error instanceof Error ? error.message : String(error) }];
      }
    }));
    return settled.flat();
  }

  async streamChat(provider: string, prompt: string, model: string,
                   emit: (event: BrowserChatEvent) => void, signal?: AbortSignal): Promise<void> {
    const adapter = this.adapters.get(provider);
    if (!adapter) throw new AdapterError("UNKNOWN_PROVIDER", `未知渠道：${provider}`, false);
    const worker = this.workers.get(provider)!;
    try {
      await worker.runExclusive(() => adapter.streamChat(prompt, model, emit, signal));
      this.markReady(provider);
    } catch (error) {
      this.recordError(provider, error);
      throw error;
    }
  }

  async completeChat(provider: string, prompt: string, model = "current"): Promise<string> {
    let content = "";
    await this.streamChat(provider, prompt, model, (event) => {
      if (event.type === "delta") content += event.content;
      if (event.type === "snapshot" || event.type === "completed") content = event.content;
    });
    if (!content.trim()) {
      throw new AdapterError("EMPTY_RESPONSE", `${provider} 网页没有返回正文`, true);
    }
    return content.trim();
  }

  async loginProvider(provider: string, timeoutMs = 10 * 60_000): Promise<ProviderStatus> {
    const existing = this.loginTasks.get(provider);
    if (existing) return existing;

    const adapter = this.adapters.get(provider);
    const worker = this.workers.get(provider);
    if (!adapter || !worker) throw new AdapterError("UNKNOWN_PROVIDER", `未知渠道：${provider}`, false);
    const task = (async () => {
      await worker.pause();
      try {
        await adapter.openForLogin();
        await adapter.waitForManualLoginSuccess(timeoutMs);
      } finally {
        await adapter.close().catch(() => undefined);
        await worker.resume();
      }
      await this.probeProvider(provider);
      return this.statuses().find((item) => item.id === provider)!;
    })();
    this.loginTasks.set(provider, task);
    try {
      return await task;
    } finally {
      if (this.loginTasks.get(provider) === task) this.loginTasks.delete(provider);
    }
  }

  async cleanupProvider(provider: string): Promise<void> {
    const adapter = this.adapters.get(provider);
    const worker = this.workers.get(provider);
    if (!adapter || !worker) throw new AdapterError("UNKNOWN_PROVIDER", `未知渠道：${provider}`, false);
    await worker.runExclusive(() => adapter.cleanupCurrentConversation());
  }

  async warmup(): Promise<Array<{ provider: string; success: boolean; error?: string }>> {
    const entries = [...this.workers.entries()];
    const settled = await Promise.allSettled(entries.map(([provider]) => this.probeProvider(provider)));
    return settled.map((result, index) => {
      const success = result.status === "fulfilled" && result.value.ready;
      return {
        provider: entries[index]![0], success,
        ...(!success ? { error: result.status === "rejected"
          ? (result.reason instanceof Error ? result.reason.message : String(result.reason))
          : result.value.reason } : {}),
      };
    });
  }

  async close(): Promise<void> {
    await Promise.all([...this.workers.values()].map((worker) => worker.close()));
  }

  async probeProvider(provider: string): Promise<BrowserProviderProbe> {
    const adapter = this.adapters.get(provider);
    const worker = this.workers.get(provider);
    if (!adapter || !worker) throw new AdapterError("UNKNOWN_PROVIDER", `未知渠道：${provider}`, false);
    if (worker.isPaused()) {
      const probe: BrowserProviderProbe = {
        state: "error", ready: false, checkedAt: new Date().toISOString(),
        url: adapter.definition.homeUrl, reason: "渠道正在等待网页登录完成",
      };
      return probe;
    }
    const probe = await worker.runExclusive(() => adapter.probe());
    this.probes.set(provider, probe);
    return probe;
  }

  async pauseProvider(provider: string): Promise<ProviderStatus> {
    const worker = this.workers.get(provider);
    if (!worker) throw new AdapterError("UNKNOWN_PROVIDER", `未知渠道：${provider}`, false);
    await worker.pause();
    return this.statuses().find((item) => item.id === provider)!;
  }

  async resumeProvider(provider: string): Promise<ProviderStatus> {
    const worker = this.workers.get(provider);
    if (!worker) throw new AdapterError("UNKNOWN_PROVIDER", `未知渠道：${provider}`, false);
    await worker.resume();
    await this.probeProvider(provider);
    return this.statuses().find((item) => item.id === provider)!;
  }

  private markReady(provider: string): void {
    this.probes.set(provider, {
      state: "ready", ready: true, checkedAt: new Date().toISOString(),
      url: this.adapters.get(provider)?.definition.homeUrl ?? "",
    });
  }

  private recordError(provider: string, caught: unknown): void {
    const error = caught instanceof AdapterError ? caught : new AdapterError(
      "UNEXPECTED_ERROR", caught instanceof Error ? caught.message : String(caught), false,
    );
    const state = error.code === "AUTH_REQUIRED" ? "login_required"
      : error.code === "HUMAN_VERIFICATION_REQUIRED" ? "verification_required" : "error";
    this.probes.set(provider, {
      state, ready: false, reason: error.message, checkedAt: new Date().toISOString(),
      url: this.adapters.get(provider)?.definition.homeUrl ?? "",
    });
  }

  private validateRequest(request: GenerateRequest): void {
    if (!request || typeof request !== "object") {
      throw new AdapterError("INVALID_REQUEST", "请求体必须是 JSON 对象", false);
    }
    if (!request.requestId?.trim()) {
      throw new AdapterError("INVALID_REQUEST", "requestId 不能为空", false);
    }
    if (!request.provider?.trim()) {
      throw new AdapterError("INVALID_REQUEST", "provider 不能为空", false);
    }
    if (!("input" in request)) {
      throw new AdapterError("INVALID_REQUEST", "input 字段不能为空", false);
    }
    if (request.cleanup && !["none", "after_success"].includes(request.cleanup)) {
      throw new AdapterError("INVALID_REQUEST", "cleanup 只支持 none 或 after_success", false);
    }
    if (request.mode && !["auto", "fast", "quality", "current"].includes(request.mode)) {
      throw new AdapterError("INVALID_REQUEST", "mode 只支持 auto、fast、quality 或 current", false);
    }
    if (request.maxAttempts !== undefined &&
        (!Number.isInteger(request.maxAttempts) || request.maxAttempts < 1 || request.maxAttempts > 3)) {
      throw new AdapterError("INVALID_REQUEST", "maxAttempts 只支持 1 到 3", false);
    }
    if (request.timeoutMs !== undefined &&
        (!Number.isFinite(request.timeoutMs) || request.timeoutMs < 1_000)) {
      throw new AdapterError("INVALID_REQUEST", "timeoutMs 不能小于 1000", false);
    }
  }

  private normalizeRequest(request: GenerateRequest): GenerateRequest {
    const value = request as GenerateRequest & Record<string, unknown>;
    return {
      ...request,
      requestId: String(value.requestId ?? value.request_id ?? value.job_id ?? ""),
      jobId: String(value.jobId ?? value.job_id ?? "") || undefined,
      idempotencyKey: String(value.idempotencyKey ?? value.idempotency_key ?? "") || undefined,
      taskType: (value.taskType ?? value.task_type) as GenerateRequest["taskType"],
      instruction: String(value.instruction ?? value.prompt ?? "") || undefined,
      outputSchema: (value.outputSchema ?? value.json_schema) as GenerateRequest["outputSchema"],
      timeoutMs: (value.timeoutMs ?? value.timeout_ms) as number | undefined,
      maxAttempts: (value.maxAttempts ?? value.max_attempts) as number | undefined,
      input: value.input ?? {},
    };
  }
}
