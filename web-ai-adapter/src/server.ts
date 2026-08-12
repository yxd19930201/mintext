import http, { type IncomingMessage, type ServerResponse } from "node:http";
import { AdapterError, normalizeError } from "./core/errors.js";
import { Orchestrator } from "./core/orchestrator.js";
import type { BatchRequest, GenerateRequest } from "./contracts.js";

const orchestrator = new Orchestrator();
const port = Number(process.env.PORT ?? 4310);

function send(response: ServerResponse, status: number, body: unknown): void {
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "access-control-allow-origin": "*",
  });
  response.end(JSON.stringify(body));
}

async function readJson<T>(request: IncomingMessage): Promise<T> {
  const chunks: Buffer[] = [];
  let length = 0;
  for await (const chunk of request) {
    const buffer = Buffer.from(chunk);
    length += buffer.length;
    if (length > 10 * 1024 * 1024) {
      throw new AdapterError("PAYLOAD_TOO_LARGE", "请求体不能超过 10MB", false);
    }
    chunks.push(buffer);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8")) as T;
  } catch {
    throw new AdapterError("INVALID_JSON", "请求体不是合法 JSON", false);
  }
}

function openAiPrompt(messages: Array<{ role?: string; content?: unknown }>): string {
  if (!Array.isArray(messages) || messages.length === 0) {
    throw new AdapterError("INVALID_REQUEST", "messages 必须是非空数组", false);
  }
  return messages.map((message) => {
    const role = message.role === "system" ? "系统要求" : message.role === "assistant" ? "此前助手" : "用户";
    const content = typeof message.content === "string"
      ? message.content
      : JSON.stringify(message.content ?? "");
    return `【${role}】\n${content}`;
  }).join("\n\n");
}

const server = http.createServer(async (request, response) => {
  if (request.method === "OPTIONS") {
    response.writeHead(204, {
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      "access-control-allow-headers": "content-type",
    });
    response.end();
    return;
  }

  try {
    if (request.method === "GET" && request.url === "/health") {
      const providers = orchestrator.statuses();
      const ok = providers.some((provider) => provider.ready);
      send(response, 200, { ok, providers });
      return;
    }
    const providerRoute = request.url?.match(/^\/v1\/providers\/([^/]+)\/(probe|pause|resume|login)$/);
    if (providerRoute) {
      const provider = decodeURIComponent(providerRoute[1]!);
      const action = providerRoute[2];
      if (action === "probe" && request.method === "GET") {
        send(response, 200, await orchestrator.probeProvider(provider));
        return;
      }
      if (action === "pause" && request.method === "POST") {
        send(response, 200, await orchestrator.pauseProvider(provider));
        return;
      }
      if (action === "resume" && request.method === "POST") {
        send(response, 200, await orchestrator.resumeProvider(provider));
        return;
      }
      if (action === "login" && request.method === "POST") {
        const body = await readJson<{ timeoutMs?: number }>(request);
        send(response, 200, await orchestrator.loginProvider(provider, body.timeoutMs));
        return;
      }
    }
    if (request.method === "GET" && request.url === "/v1/providers") {
      send(response, 200, { providers: orchestrator.statuses() });
      return;
    }
    if (request.method === "GET" && request.url === "/v1/capabilities") {
      send(response, 200, {
        providers: orchestrator.statuses().map((provider) => ({
          id: provider.id, enabled: provider.enabled, structuredJson: true,
          independentConversation: true, modes: ["fast", "quality", "current"],
          persistentIdempotency: true, maxPayloadBytes: 10 * 1024 * 1024,
        })),
      });
      return;
    }
    if (request.method === "GET" && request.url === "/v1/chat/models") {
      send(response, 200, { models: await orchestrator.chatModels() });
      return;
    }
    if (request.method === "POST" && request.url === "/v1/chat/completions") {
      const body = await readJson<{
        model?: string;
        provider?: string;
        messages?: Array<{ role?: string; content?: unknown }>;
      }>(request);
      const provider = body.provider ?? body.model ?? "deepseek";
      if (!provider) throw new AdapterError("INVALID_REQUEST", "model 或 provider 不能为空", false);
      const content = await orchestrator.completeChat(
        provider,
        openAiPrompt(body.messages ?? []),
        provider === "deepseek" ? "fast" : "current",
      );
      send(response, 200, {
        id: `web-${Date.now()}`,
        object: "chat.completion",
        created: Math.floor(Date.now() / 1000),
        model: provider,
        choices: [{ index: 0, message: { role: "assistant", content }, finish_reason: "stop" }],
        usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
      });
      return;
    }
    if (request.method === "POST" && request.url === "/v1/chat/stream") {
      const body = await readJson<{ requestId?: string; provider?: string; model?: string; prompt?: string; cleanup?: string }>(request);
      if (!body.provider || !body.prompt) throw new AdapterError("INVALID_REQUEST", "provider 和 prompt 不能为空", false);
      response.writeHead(200, {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache",
        "connection": "keep-alive",
        "access-control-allow-origin": "*",
      });
      const controller = new AbortController();
      response.once("close", () => controller.abort());
      try {
        await orchestrator.streamChat(body.provider, body.prompt, body.model ?? "current", (event) => {
          if (!response.writableEnded) response.write(`data: ${JSON.stringify(event)}\n\n`);
        }, controller.signal);
        if (body.cleanup === "after_success" && !controller.signal.aborted) {
          await orchestrator.cleanupProvider(body.provider).catch(() => undefined);
        }
      } catch (caught) {
        const error = normalizeError(caught);
        if (!response.writableEnded) response.write(`data: ${JSON.stringify({ type: "failed", error: error.message })}\n\n`);
      }
      if (!response.writableEnded) response.end();
      return;
    }
    if (request.method === "POST" && request.url === "/v1/generate") {
      const body = await readJson<GenerateRequest>(request);
      send(response, 200, await orchestrator.generate(body));
      return;
    }
    if (request.method === "POST" && request.url === "/v1/generate/status") {
      const body = await readJson<GenerateRequest>(request);
      send(response, 200, await orchestrator.lookup(body));
      return;
    }
    if (request.method === "POST" && request.url === "/v1/generate/batch") {
      const body = await readJson<BatchRequest>(request);
      if (!Array.isArray(body.requests) || body.requests.length === 0) {
        throw new AdapterError("INVALID_REQUEST", "requests 必须是非空数组", false);
      }
      send(response, 200, { results: await orchestrator.generateBatch(body.requests) });
      return;
    }
    send(response, 404, { error: { code: "NOT_FOUND", message: "接口不存在" } });
  } catch (caught) {
    const error = normalizeError(caught);
    if (response.headersSent) {
      if (!response.writableEnded) response.end();
      return;
    }
    const status = error.code === "UNKNOWN_PROVIDER" ? 404 : 400;
    send(response, status, {
      error: {
        code: error.code,
        message: error.message,
        retryable: error.retryable,
        details: error.details,
      },
    });
  }
});

if (process.env.WEB_AI_PREWARM !== "false") {
  const results = await orchestrator.warmup();
  console.log(`Provider warmup: ${JSON.stringify(results)}`);
}

server.listen(port, "127.0.0.1", () => {
  console.log(`Web AI Adapter listening on http://127.0.0.1:${port}`);
});

async function shutdown(): Promise<void> {
  server.close();
  await orchestrator.close();
  process.exit(0);
}

process.once("SIGINT", shutdown);
process.once("SIGTERM", shutdown);
