import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import type { GenerateRequest, GenerateResponse } from "../contracts.js";
import { AdapterError } from "./errors.js";

interface StoredResult {
  key: string;
  fingerprint: string;
  fingerprintVersion?: number;
  response: GenerateResponse;
}

export class IdempotencyStore {
  constructor(private readonly root: string) {}

  keyFor(request: GenerateRequest): string {
    return (request.idempotencyKey || request.jobId || request.requestId).trim();
  }

  fingerprint(request: GenerateRequest): string {
    const stable = {
      provider: request.provider,
      input: request.input,
      taskType: request.taskType,
      instruction: request.instruction,
      outputSchema: request.outputSchema,
      mode: request.mode,
      cleanup: request.cleanup,
      timeoutMs: request.timeoutMs,
      maxAttempts: request.maxAttempts,
    };
    return crypto.createHash("sha256").update(JSON.stringify(stable)).digest("hex");
  }

  private filename(key: string): string {
    const digest = crypto.createHash("sha256").update(key).digest("hex");
    return path.join(this.root, `${digest}.json`);
  }

  async load(request: GenerateRequest): Promise<GenerateResponse | null> {
    const key = this.keyFor(request);
    try {
      const stored = JSON.parse(await fs.readFile(this.filename(key), "utf8")) as StoredResult;
      // Idempotency protects adopted outputs. A model/schema failure must remain
      // retryable when an operator resumes the production job with the same key.
      if (!stored.response.success) return null;
      if (stored.fingerprintVersion === 2 && stored.fingerprint !== this.fingerprint(request)) {
        throw new AdapterError(
          "IDEMPOTENCY_KEY_CONFLICT",
          `幂等键 ${key} 已用于不同请求`,
          false,
        );
      }
      return { ...stored.response, meta: { ...stored.response.meta, cached: true } };
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
      throw error;
    }
  }

  async save(request: GenerateRequest, response: GenerateResponse): Promise<void> {
    await fs.mkdir(this.root, { recursive: true });
    const key = this.keyFor(request);
    const destination = this.filename(key);
    const temporary = `${destination}.${process.pid}.${Date.now()}.tmp`;
    const stored: StoredResult = { key, fingerprint: this.fingerprint(request), fingerprintVersion: 2, response };
    await fs.writeFile(temporary, JSON.stringify(stored), "utf8");
    await fs.rename(temporary, destination);
  }
}
