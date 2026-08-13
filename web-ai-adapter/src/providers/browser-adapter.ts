import fs from "node:fs/promises";
import path from "node:path";
import net from "node:net";
import { spawn, type ChildProcess } from "node:child_process";
import { chromium, type Browser, type BrowserContext, type Locator, type Page } from "playwright";
import { AdapterError } from "../core/errors.js";
import { extractJsonText, parseJsonText, JSON_CLOSE, JSON_OPEN } from "../core/json-envelope.js";
import type { ProviderId, ResolvedExecutionMode } from "../contracts.js";
import type { ProviderDefinition } from "./definitions.js";
import {
  channelTryOrder,
  playwrightChannelOption,
  profilePathForChannel,
  readConfiguredBrowserChannel,
  resolveBrowserChannel,
  resolveSystemBrowserExecutable,
  systemBrowserCandidates,
  pathExists,
} from "./browser-channel.js";

export interface BrowserGeneration {
  rawText: string;
  conversationId: string | null;
  /** True when the answer was harvested from an existing page conversation. */
  recovered?: boolean;
  /** True when a timed-out wait later found a stable answer on the page. */
  salvagedAfterTimeout?: boolean;
}

/** Collapse whitespace so page text and prompt compare stably. */
export function normalizePromptText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

/**
 * Heuristic: is this page still showing the same problem we just asked?
 * Long design prompts rarely appear verbatim in full; match head + mid + tail
 * slices.  Head + mid alone is unsafe for chained novel work because draft,
 * audit and revision prompts share the same system rules and large context.
 * That previously made the draft answer look reusable for the audit request.
 */
export function pageLikelyContainsPrompt(pageText: string, prompt: string): boolean {
  const page = normalizePromptText(pageText);
  const compact = normalizePromptText(prompt);
  if (!compact) return false;
  if (compact.length <= 64) return page.includes(compact);
  const head = compact.slice(0, 96);
  if (!page.includes(head)) return false;
  const midStart = Math.min(Math.max(0, Math.floor(compact.length / 2) - 48), Math.max(0, compact.length - 96));
  const mid = compact.slice(midStart, midStart + 96);
  if (mid.length >= 24 && !page.includes(mid)) return false;
  const tail = compact.slice(-128);
  return tail.length < 24 || page.includes(tail);
}

/** Prefer reusable answers that already look like structured model output. */
export function looksLikeReusableModelAnswer(rawText: string): boolean {
  const text = rawText.trim();
  if (!text) return false;
  if (text.includes(JSON_OPEN) || text.includes("```json")) return true;
  try {
    parseJsonText(extractJsonText(text));
    return true;
  } catch {
    return false;
  }
}

export function answerFingerprint(rawText: string): string {
  return normalizePromptText(rawText).slice(0, 4_000);
}

export interface GenerationWaitBudget {
  /** Expected wait for a normal completion. */
  softMs: number;
  /** Absolute ceiling when the page is still healthy and generating. */
  hardMs: number;
}

/**
 * Soft timeout is the normal budget. Hard timeout is longer so deep thinking
 * can finish when nothing is actually broken (no exception / page crash / auth).
 */
export function resolveGenerationWaitBudget(timeoutMs: number): GenerationWaitBudget {
  const softMs = Math.max(5_000, Math.floor(timeoutMs));
  const extraMs = Math.max(0, Number(process.env.WEB_AI_HEALTHY_EXTRA_MS ?? 180_000));
  const hardCapMs = Math.max(softMs, Number(process.env.WEB_AI_HARD_TIMEOUT_MS ?? 600_000));
  const hardMs = Math.min(hardCapMs, Math.max(softMs + extraMs, softMs * 2));
  return { softMs, hardMs };
}

export interface HealthyWaitDecisionInput {
  now: number;
  softDeadline: number;
  hardDeadline: number;
  pageAlive: boolean;
  interrupted: boolean;
  generating: boolean;
  contentProgressed: boolean;
  lastProgressAt: number;
  /** After soft deadline, how long idle (no progress, not generating) before stop. */
  idleStuckMs?: number;
}

/**
 * After the soft deadline, keep waiting only when the browser/model still look
 * healthy and either are actively generating or recently made progress.
 */
export function shouldContinueHealthyWait(input: HealthyWaitDecisionInput): boolean {
  if (input.now >= input.hardDeadline) return false;
  if (!input.pageAlive || input.interrupted) return false;
  if (input.now < input.softDeadline) return true;
  if (input.generating || input.contentProgressed) return true;
  const idleStuckMs = input.idleStuckMs ?? 45_000;
  return input.now - input.lastProgressAt < idleStuckMs;
}

export interface BrowserChatModel {
  id: string;
  name: string;
  available: boolean;
  details?: Record<string, unknown>;
}

export interface BrowserProviderProbe {
  state: "login_required" | "verification_required" | "ready" | "error";
  ready: boolean;
  reason?: string;
  checkedAt: string;
  url: string;
}

export function classifyAuthenticationState(
  label: string,
  title: string,
  body: string,
  url: string,
  loginVisible: boolean,
  credentialVisible: boolean,
): Pick<BrowserProviderProbe, "state" | "reason"> | null {
  const visible = `${title}\n${body}`;
  if (/账号已被禁言|账户已被禁言|account (?:is |has been )?(?:restricted|suspended)|temporarily restricted/i.test(visible)) {
    return {
      state: "verification_required",
      reason: `${label} 账号当前受限/禁言，网页版暂时不能提交生成任务，请更换账号或等待限制解除`,
    };
  }
  if (/正在验证您是否是真人|请稍候|verify you are human|checking your browser|just a moment|challenge-platform/i.test(`${title}\n${body}`)) {
    return { state: "verification_required", reason: `${label} 需要在系统 Chrome 或 Edge 中完成人工真人验证` };
  }
  if (loginVisible || credentialVisible || /\/login|\/signin|auth\./i.test(url.toLowerCase())) {
    return { state: "login_required", reason: `${label} 尚未在青玉专用浏览器档案中登录` };
  }
  return null;
}

export async function findEditableLocator(page: Page, selectors: string[], timeoutMs: number): Promise<Locator | null> {
  const deadline = Date.now() + timeoutMs;
  do {
    for (const selector of selectors) {
      const matches = page.locator(selector);
      const count = Math.min(await matches.count().catch(() => 0), 20);
      for (let index = 0; index < count; index += 1) {
        const locator = matches.nth(index);
        const usable = await Promise.all([
          locator.isVisible().catch(() => false),
          locator.isEnabled().catch(() => false),
          locator.isEditable().catch(() => false),
        ]);
        if (usable.every(Boolean)) return locator;
      }
    }
    await page.waitForTimeout(25);
  } while (Date.now() < deadline);
  return null;
}

export async function fillStablePrompt(
  page: Page, selectors: string[], prompt: string, timeoutMs: number, label: string,
): Promise<Locator> {
  const deadline = Date.now() + timeoutMs;
  let lastError = "";
  while (Date.now() < deadline) {
    const input = await findEditableLocator(page, selectors, Math.min(1_000, Math.max(100, deadline - Date.now())));
    if (input) {
      try {
        await input.fill(prompt, { timeout: 1_500 });
        if (await input.isVisible().catch(() => false)) return input;
      } catch (caught) {
        lastError = caught instanceof Error ? caught.message : String(caught);
      }
    }
    await page.waitForTimeout(25);
  }
  throw new AdapterError(
    "INPUT_NOT_FOUND",
    `${label} 没有找到稳定、可编辑的输入框，请重新检测登录状态`,
    true,
    lastError ? { cause: lastError.slice(0, 500) } : undefined,
  );
}

export type BrowserChatEvent =
  | { type: "started" | "waiting" }
  | { type: "delta" | "snapshot" | "reasoning_delta" | "reasoning_snapshot"; content: string }
  | { type: "completed"; content: string }
  | { type: "failed"; error: string };

export function selectLongestResponseCandidate(candidates: string[]): string {
  return candidates
    .map((candidate) => candidate.trim())
    .reduce((longest, candidate) => candidate.length > longest.length ? candidate : longest, "");
}

export function splitDeepSeekDomCandidates(
  candidates: Array<{ text: string; classNames: string[] }>,
): { reasoning: string[]; answer: string[] } {
  const containsClass = (classNames: string[], expected: string): boolean =>
    classNames.some((value) => value.split(/\s+/).includes(expected));
  const reasoning: string[] = [];
  const answer: string[] = [];
  for (const candidate of candidates) {
    const text = candidate.text.trim();
    if (!text) continue;
    if (containsClass(candidate.classNames, "ds-think-content")) reasoning.push(text);
    else if (containsClass(candidate.classNames, "ds-assistant-message-main-content")) answer.push(text);
  }
  return { reasoning: [...new Set(reasoning)], answer: [...new Set(answer)] };
}

export class BrowserProviderAdapter {
  private browser: Browser | null = null;
  private browserProcess: ChildProcess | null = null;
  private cdpStatePath: string | null = null;
  private context: BrowserContext | null = null;
  private page: Page | null = null;
  /** Answers that already failed schema/validation; do not re-offer them. */
  private rejectedAnswerFingerprints = new Set<string>();

  constructor(
    public readonly definition: ProviderDefinition,
    private readonly profileRoot: string,
    private readonly headless: boolean,
  ) {}

  get id(): ProviderId {
    return this.definition.id;
  }

  private async ensurePage(): Promise<Page> {
    if (this.page && !this.page.isClosed()) return this.page;
    const providerPrefix = `WEB_AI_${this.definition.id.toUpperCase()}_`;
    const providerRoot = process.env[`${providerPrefix}PROFILE_ROOT`] ?? this.profileRoot;
    const configuredChannel = readConfiguredBrowserChannel(this.definition.id);
    const channel = await resolveBrowserChannel(configuredChannel);
    const headlessOverride = process.env[`${providerPrefix}HEADLESS`];
    const headless = headlessOverride == null ? this.headless : headlessOverride === "true";
    const startMinimized = process.env[`${providerPrefix}START_MINIMIZED`] === "true";
    const lastErrors: string[] = [];
    try {
      const useSystemCdp = !headless && channel !== "bundled"
        && process.env[`${providerPrefix}USE_SYSTEM_CDP`] !== "false";
      if (useSystemCdp) {
        await this.launchSystemCdp({
          providerRoot,
          preferredChannel: channel as "chrome" | "msedge",
          startMinimized,
          lastErrors,
        });
      } else {
        const profilePath = profilePathForChannel(providerRoot, this.definition.id, channel);
        await fs.mkdir(profilePath, { recursive: true });
        this.context = await chromium.launchPersistentContext(profilePath, {
          headless,
          chromiumSandbox: true,
          viewport: { width: 1440, height: 960 },
          ...playwrightChannelOption(channel),
        });
      }
    } catch (error) {
      const detail = [error instanceof Error ? error.message : String(error), ...lastErrors]
        .filter(Boolean)
        .join("；");
      throw new AdapterError(
        "BROWSER_NOT_AVAILABLE",
        channel === "bundled"
          ? "Playwright Chromium 不可用，请运行 npx playwright install chromium"
          : `本机浏览器不可用（优先 Edge，其次 Chrome）；请安装 Microsoft Edge 或 Google Chrome，或设置 WEB_AI_BROWSER_CHANNEL=bundled 后安装 Playwright Chromium`,
        false,
        detail,
      );
    }
    this.page = this.context!.pages()[0] ?? (await this.context!.newPage());
    return this.page;
  }

  /**
   * Launch system Edge/Chrome via CDP. Always pair executable with a matching
   * user-data-dir brand (Chrome + Edge profile exits immediately).
   * Tries Edge then Chrome when preferred is auto / preferred fails.
   */
  private async launchSystemCdp(options: {
    providerRoot: string;
    preferredChannel: "chrome" | "msedge" | "auto";
    startMinimized: boolean;
    lastErrors: string[];
  }): Promise<void> {
    const order = channelTryOrder(options.preferredChannel);
    if (order.length === 0) {
      throw new Error("没有可用的系统浏览器渠道");
    }

    // Reuse an existing healthy CDP session for any candidate profile first.
    for (const name of order) {
      const profilePath = profilePathForChannel(options.providerRoot, this.definition.id, name);
      const cdpStatePath = path.join(profilePath, ".shenbi-cdp.json");
      const existingEndpoint = await this.readReusableDebugEndpoint(cdpStatePath);
      if (!existingEndpoint) continue;
      try {
        this.browser = await chromium.connectOverCDP(existingEndpoint);
        this.context = this.browser.contexts()[0] ?? null;
        if (this.context) {
          this.cdpStatePath = cdpStatePath;
          return;
        }
        await this.browser.close().catch(() => undefined);
        this.browser = null;
      } catch (error) {
        options.lastErrors.push(`${name} 复用 CDP 失败: ${error instanceof Error ? error.message : String(error)}`);
      }
    }

    for (const name of order) {
      let executable: string | null = null;
      for (const candidate of systemBrowserCandidates(name)) {
        if (await pathExists(candidate)) {
          executable = candidate;
          break;
        }
      }
      if (!executable) {
        options.lastErrors.push(`${name} 未安装`);
        continue;
      }

      const profilePath = profilePathForChannel(options.providerRoot, this.definition.id, name);
      await fs.mkdir(profilePath, { recursive: true });
      const cdpStatePath = path.join(profilePath, ".shenbi-cdp.json");
      const port = await this.reserveDebugPort();
      const args = [
        `--user-data-dir=${profilePath}`,
        `--remote-debugging-port=${port}`,
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        ...(options.startMinimized ? ["--start-minimized"] : []),
        this.definition.homeUrl,
      ];
      const child = spawn(executable, args, {
        stdio: "ignore", windowsHide: false, detached: true,
      });
      child.unref();
      const endpoint = `http://127.0.0.1:${port}`;
      try {
        await this.waitForDebugEndpoint(endpoint, child);
        await fs.writeFile(cdpStatePath, JSON.stringify({
          endpoint,
          pid: child.pid,
          provider: this.id,
          channel: name,
          updatedAt: new Date().toISOString(),
        }), "utf8");
        this.browserProcess = child;
        this.cdpStatePath = cdpStatePath;
        this.browser = await chromium.connectOverCDP(endpoint);
        this.context = this.browser.contexts()[0] ?? null;
        if (!this.context) throw new Error("系统浏览器没有提供可连接的默认上下文");
        return;
      } catch (error) {
        options.lastErrors.push(
          `${name} 启动失败: ${error instanceof Error ? error.message : String(error)}`,
        );
        if (child.exitCode == null) child.kill();
        this.browserProcess = null;
        await this.browser?.close().catch(() => undefined);
        this.browser = null;
        this.context = null;
        await fs.unlink(cdpStatePath).catch(() => undefined);
      }
    }

    // Last resort: let resolveSystemBrowserExecutable throw a clear message.
    await resolveSystemBrowserExecutable(options.preferredChannel);
    throw new Error(options.lastErrors.join("；") || "系统浏览器启动失败");
  }

  async openForLogin(): Promise<void> {
    const page = await this.ensurePage();
    await page.goto(this.definition.homeUrl, { waitUntil: "domcontentloaded" });
  }

  async warmup(): Promise<void> {
    const result = await this.probe();
    if (!result.ready) {
      const code = result.state === "login_required" ? "AUTH_REQUIRED"
        : result.state === "verification_required" ? "HUMAN_VERIFICATION_REQUIRED"
        : "PROVIDER_NOT_READY";
      throw new AdapterError(code, result.reason ?? `${this.definition.label} 当前不可用`, false);
    }
  }

  async probe(): Promise<BrowserProviderProbe> {
    const checkedAt = new Date().toISOString();
    try {
      const page = await this.ensurePage();
      if (!page.url().startsWith(this.definition.homeUrl)) {
        await page.goto(this.definition.homeUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
      }
      await page.waitForTimeout(750);
      const issue = await this.authenticationIssue(page);
      if (issue) return { ...issue, ready: false, checkedAt, url: page.url() };
      const input = await this.findEditableInput(page, this.id === "chatgpt" ? 15_000 : 5_000);
      if (!input) {
        return {
          state: "error", ready: false, checkedAt, url: page.url(),
          reason: `${this.definition.label} 页面已打开，但没有发现可编辑的输入框`,
        };
      }
      return { state: "ready", ready: true, checkedAt, url: page.url() };
    } catch (caught) {
      const error = caught instanceof Error ? caught.message : String(caught);
      return { state: "error", ready: false, checkedAt, url: this.page?.url() ?? this.definition.homeUrl, reason: error };
    }
  }

  async waitForManualLoginSuccess(timeoutMs = 10 * 60_000): Promise<void> {
    const page = await this.ensurePage();
    const deadline = Date.now() + timeoutMs;

    // Finish as soon as the authenticated chat composer becomes usable. The
    // old login flow waited for the whole browser to close, which left the
    // desktop button stuck on "waiting" after a successful web login.
    while (Date.now() < deadline) {
      if (page.isClosed()) return;
      const issue = await this.authenticationIssue(page).catch(() => null);
      const input = issue
        ? null
        : await this.findEditableInput(page, 750).catch(() => null);
      if (!issue && input) {
        // Allow Chromium to flush the newly issued cookies to the profile.
        await page.waitForTimeout(1_000);
        return;
      }
      await page.waitForTimeout(500);
    }

    throw new AdapterError(
      "LOGIN_TIMEOUT",
      `${this.definition.label} 登录等待超时；请确认已进入聊天页面且输入框可以使用`,
      false,
    );
  }

  async waitForManualLoginClose(timeoutMs = 10 * 60_000): Promise<void> {
    const page = await this.ensurePage();
    const context = this.context;
    if (!context) throw new AdapterError("BROWSER_CLOSED", "浏览器没有启动", false);
    try {
      await Promise.race([
        page.waitForEvent("close", { timeout: timeoutMs }),
        context.waitForEvent("close", { timeout: timeoutMs }),
      ]);
    } catch (error) {
      throw new AdapterError(
        "LOGIN_TIMEOUT",
        `${this.definition.label} 登录等待超时；完成登录后需要关闭整个浏览器窗口`,
        false,
        error instanceof Error ? error.message : String(error),
      );
    }
  }

  async close(): Promise<void> {
    if (this.browser) await this.browser.close().catch(() => undefined);
    else await this.context?.close().catch(() => undefined);
    if (this.browserProcess && this.browserProcess.exitCode == null) {
      this.browserProcess.kill();
    }
    this.browser = null;
    this.browserProcess = null;
    this.context = null;
    this.page = null;
    if (this.cdpStatePath) await fs.unlink(this.cdpStatePath).catch(() => undefined);
    this.cdpStatePath = null;
  }

  async disconnect(): Promise<void> {
    if (!this.browser) {
      await this.context?.close().catch(() => undefined);
    }
    this.browser = null;
    this.browserProcess = null;
    this.context = null;
    this.page = null;
  }

  private reserveDebugPort(): Promise<number> {
    return new Promise((resolve, reject) => {
      const server = net.createServer();
      server.once("error", reject);
      server.listen(0, "127.0.0.1", () => {
        const address = server.address();
        const port = typeof address === "object" && address ? address.port : 0;
        server.close((error) => error ? reject(error) : resolve(port));
      });
    });
  }

  private async waitForDebugEndpoint(endpoint: string, processHandle: ChildProcess): Promise<void> {
    const deadline = Date.now() + 20_000;
    while (Date.now() < deadline) {
      if (processHandle.exitCode != null) throw new Error(`系统浏览器提前退出：${processHandle.exitCode}`);
      try {
        const response = await fetch(`${endpoint}/json/version`);
        if (response.ok) return;
      } catch { /* browser is still starting */ }
      await new Promise((resolve) => setTimeout(resolve, 150));
    }
    throw new Error("等待系统浏览器调试端口超时");
  }

  private async readReusableDebugEndpoint(statePath: string): Promise<string | null> {
    try {
      const saved = JSON.parse(await fs.readFile(statePath, "utf8")) as { endpoint?: string };
      if (!saved.endpoint?.startsWith("http://127.0.0.1:")) return null;
      const response = await fetch(`${saved.endpoint}/json/version`);
      if (response.ok) return saved.endpoint;
    } catch { /* stale or missing state is replaced below */ }
    await fs.unlink(statePath).catch(() => undefined);
    return null;
  }

  /**
   * Mark a harvested answer as unusable so the next attempt will re-submit
   * instead of looping on the same invalid page content.
   */
  markRejectedRecovery(rawText: string): void {
    this.rejectedAnswerFingerprints.add(answerFingerprint(rawText));
    if (this.rejectedAnswerFingerprints.size > 40) {
      const first = this.rejectedAnswerFingerprints.values().next().value;
      if (first) this.rejectedAnswerFingerprints.delete(first);
    }
  }

  async generate(
    prompt: string,
    timeoutMs: number,
    mode: ResolvedExecutionMode = "quality",
  ): Promise<BrowserGeneration> {
    const page = await this.ensurePage();
    try {
      // Second try / user re-run: if the previous wait only timed out while the
      // model was still thinking, the finished answer may already be on screen
      // for the same problem. Reuse it instead of opening a new chat.
      const recovered = await this.tryRecoverFromCurrentConversation(prompt);
      if (recovered) return recovered;

      const conversationIdsBefore = await this.collectConversationIds(page);
      await this.startIndependentConversation(page, timeoutMs);
      await this.ensureAuthenticated(page);
      await this.applyExecutionMode(page, mode);
      await this.disableUnneededFeatures(page);

      const baselineText = await page.locator("body").innerText();
      const baselineEnvelopeCount = this.countOccurrences(baselineText, JSON_CLOSE);
      const promptEnvelopeCount = this.countOccurrences(prompt, JSON_CLOSE);
      const baselineAssistantFingerprints = new Set(
        (await this.collectAssistantTexts(page)).map(answerFingerprint),
      );
      const input = await this.fillPrompt(page, prompt, timeoutMs);
      const send = await this.firstVisible(page, this.definition.sendSelectors, 5_000);
      if (send) await send.click();
      else await input.press("Enter");

      try {
        await this.waitForResponse(
          page,
          baselineEnvelopeCount + promptEnvelopeCount + 1,
          baselineAssistantFingerprints,
          timeoutMs,
        );
      } catch (waitError) {
        if (!(waitError instanceof AdapterError) || waitError.code !== "GENERATION_TIMEOUT") {
          throw waitError;
        }
        // Final harvest after the hard healthy-wait budget; answer may still
        // have finished while we were deciding to stop.
        const salvaged = await this.salvageAnswerAfterTimeout(page, baselineAssistantFingerprints, 15_000);
        if (salvaged) {
          const conversationId = await this.findNewConversationId(page, conversationIdsBefore);
          return { rawText: salvaged, conversationId, salvagedAfterTimeout: true };
        }
        throw waitError;
      }
      const rawText = await this.extractFinalAnswer(page);
      const conversationId = await this.findNewConversationId(page, conversationIdsBefore);

      return { rawText, conversationId };
    } catch (caught) {
      const diagnosticsRoot = path.resolve(
        process.env.WEB_AI_DIAGNOSTICS_ROOT ?? ".runtime/diagnostics",
      );
      await fs.mkdir(diagnosticsRoot, { recursive: true });
      const diagnosticPath = path.join(
        diagnosticsRoot,
        `${this.id}-${new Date().toISOString().replace(/[:.]/g, "-")}.png`,
      );
      await page.screenshot({ path: diagnosticPath, fullPage: true }).catch(() => undefined);
      if (caught instanceof AdapterError) {
        throw new AdapterError(caught.code, caught.message, caught.retryable, {
          original: caught.details,
          diagnosticPath,
        });
      }
      throw caught;
    }
  }

  private async tryRecoverFromCurrentConversation(prompt: string): Promise<BrowserGeneration | null> {
    if (!this.page || this.page.isClosed()) return null;
    const page = this.page;
    if (!page.url().startsWith(this.definition.homeUrl.replace(/\/$/, ""))) return null;

    const bodyText = await page.locator("body").innerText().catch(() => "");
    if (!pageLikelyContainsPrompt(bodyText, prompt)) return null;

    // If the model is still thinking, give it a short extra window before reusing.
    const graceDeadline = Date.now() + 25_000;
    while (Date.now() < graceDeadline) {
      if (await this.isGenerationIdle(page)) break;
      await page.waitForTimeout(250);
    }

    let rawText: string;
    try {
      rawText = await this.extractFinalAnswer(page);
    } catch {
      return null;
    }
    if (!looksLikeReusableModelAnswer(rawText)) return null;
    if (this.rejectedAnswerFingerprints.has(answerFingerprint(rawText))) return null;

    return {
      rawText,
      conversationId: this.extractConversationId(page.url()),
      recovered: true,
    };
  }

  private async salvageAnswerAfterTimeout(
    page: Page,
    baselineAssistantFingerprints: Set<string>,
    graceMs: number,
  ): Promise<string | null> {
    const deadline = Date.now() + graceMs;
    let lastCandidate = "";
    let stableSince = Date.now();
    while (Date.now() < deadline) {
      const assistantTexts = await this.collectAssistantTexts(page);
      const candidate = selectLongestResponseCandidate(
        assistantTexts.filter((text) => !baselineAssistantFingerprints.has(answerFingerprint(text))),
      );
      if (candidate && candidate !== lastCandidate) {
        lastCandidate = candidate;
        stableSince = Date.now();
      } else if (
        candidate
        && Date.now() - stableSince >= 1_500
        && await this.isGenerationIdle(page)
        && looksLikeReusableModelAnswer(candidate)
        && !this.rejectedAnswerFingerprints.has(answerFingerprint(candidate))
      ) {
        return candidate;
      }
      await page.waitForTimeout(200);
    }
    if (
      lastCandidate
      && looksLikeReusableModelAnswer(lastCandidate)
      && !this.rejectedAnswerFingerprints.has(answerFingerprint(lastCandidate))
      && await this.isGenerationIdle(page)
    ) {
      return lastCandidate;
    }
    return null;
  }

  async detectChatModels(): Promise<BrowserChatModel[]> {
    const page = await this.ensurePage();
    if (!page.url().startsWith(this.definition.homeUrl)) {
      await page.goto(this.definition.homeUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
    }
    await this.ensureAuthenticated(page);
    const input = await this.findEditableInput(page, this.id === "chatgpt" ? 15_000 : 3_000);
    if (!input) {
      const pageTitle = await page.title().catch(() => "");
      throw new AdapterError(
        "MODEL_DISCOVERY_PENDING",
        `${this.definition.label} 未发现可用输入框或模型菜单（${pageTitle || "页面未完成加载"} · ${page.url()}）`,
        false,
      );
    }
    if (this.id === "deepseek") {
      const result: BrowserChatModel[] = [];
      const fast = await this.findVisibleOption(page, this.definition.fastModeSelectors);
      const quality = await this.findVisibleOption(page, this.definition.qualityModeSelectors);
      if (fast) result.push({ id: "fast", name: "DeepSeek 网页 · 快速模式", available: true });
      if (quality) result.push({ id: "quality", name: "DeepSeek 网页 · 质量模式", available: true });
      return result.length ? result : [{ id: "current", name: "DeepSeek 网页 · 当前模式", available: true }];
    }
    const menu = await this.firstVisible(page, this.definition.modelMenuSelectors, 5_000);
    if (!menu) return [];
    await menu.click();
    await page.waitForTimeout(200);
    const labels: string[] = [];
    for (const selector of this.definition.modelOptionSelectors) {
      const values = await page.locator(selector).allInnerTexts().catch(() => []);
      labels.push(...values);
    }
    await page.keyboard.press("Escape").catch(() => undefined);
    return [...new Set(labels.map((value) => value.trim().replace(/\s+/g, " ")).filter((value) => value.length > 0 && value.length < 120))]
      .map((label) => ({ id: label, name: `ChatGPT 网页 · ${label}`, available: true }));
  }

  async streamChat(
    prompt: string,
    model: string,
    emit: (event: BrowserChatEvent) => void,
    signal?: AbortSignal,
    timeoutMs = 300_000,
  ): Promise<void> {
    const page = await this.ensurePage();
    await this.startIndependentConversation(page, timeoutMs);
    await this.ensureAuthenticated(page);
    if (this.id === "deepseek" && ["fast", "quality"].includes(model)) {
      await this.applyExecutionMode(page, model as ResolvedExecutionMode);
    } else if (this.id === "chatgpt" && model && model !== "current") {
      await this.selectChatModel(page, model);
    }
    await this.disableUnneededFeatures(page);
    const baselineAssistantCount = (await this.collectAssistantTexts(page)).length;
    const deepSeekBaseline = this.id === "deepseek"
      ? await this.collectDeepSeekAssistantParts(page)
      : null;
    const input = await this.fillPrompt(page, prompt, timeoutMs);
    const send = await this.firstVisible(page, this.definition.sendSelectors, 5_000);
    if (send) await send.click(); else await input.press("Enter");
    emit({ type: "started" });
    const budget = resolveGenerationWaitBudget(timeoutMs);
    const softDeadline = Date.now() + budget.softMs;
    const hardDeadline = Date.now() + budget.hardMs;
    let latest = "";
    let latestReasoning = "";
    let answerStarted = false;
    let stableSince = Date.now();
    let lastProgressAt = Date.now();
    let waitingSent = false;
    while (true) {
      const now = Date.now();
      if (signal?.aborted) {
        await this.stopCurrentGeneration(page);
        return;
      }
      let candidate = "";
      let reasoningGrew = false;
      if (this.id === "deepseek") {
        const parts = await this.collectDeepSeekAssistantParts(page);
        const reasoning = selectLongestResponseCandidate(
          parts.reasoning.slice(deepSeekBaseline?.reasoning.length ?? 0),
        );
        if (!answerStarted && reasoning && reasoning !== latestReasoning) {
          reasoningGrew = true;
          if (reasoning.startsWith(latestReasoning)) {
            emit({ type: "reasoning_delta", content: reasoning.slice(latestReasoning.length) });
          } else {
            emit({ type: "reasoning_snapshot", content: reasoning });
          }
          latestReasoning = reasoning;
        }
        candidate = selectLongestResponseCandidate(
          parts.answer.slice(deepSeekBaseline?.answer.length ?? 0),
        );
      } else {
        const texts = await this.collectAssistantTexts(page);
        const candidates = texts.slice(baselineAssistantCount);
        candidate = selectLongestResponseCandidate(candidates);
      }
      if (candidate && candidate !== latest) {
        answerStarted = true;
        if (candidate.startsWith(latest)) emit({ type: "delta", content: candidate.slice(latest.length) });
        else emit({ type: "snapshot", content: candidate });
        latest = candidate;
        stableSince = Date.now();
        lastProgressAt = Date.now();
      } else if (reasoningGrew) {
        lastProgressAt = Date.now();
      } else if (!candidate && !waitingSent && now + 2_000 < hardDeadline) {
        waitingSent = true;
        emit({ type: "waiting" });
      } else if (latest && Date.now() - stableSince >= 1_200 && await this.isGenerationIdle(page)) {
        emit({ type: "completed", content: latest });
        return;
      }

      const generating = !(await this.isGenerationIdle(page));
      const health = await this.assessPageGenerationHealth(page);
      const keepWaiting = shouldContinueHealthyWait({
        now,
        softDeadline,
        hardDeadline,
        pageAlive: health.pageAlive,
        interrupted: health.interrupted,
        generating,
        contentProgressed: false,
        lastProgressAt,
      });
      if (!keepWaiting) break;
      await page.waitForTimeout(120);
    }
    throw new AdapterError("GENERATION_TIMEOUT", `${this.definition.label} 聊天回复超时`, true);
  }

  private async findVisibleOption(page: Page, selectors: string[]): Promise<boolean> {
    if (await this.firstVisible(page, selectors, 250)) return true;
    const menu = await this.firstVisible(page, this.definition.modeMenuSelectors, 500);
    if (!menu) return false;
    await menu.click();
    const found = Boolean(await this.firstVisible(page, selectors, 750));
    await page.keyboard.press("Escape").catch(() => undefined);
    return found;
  }

  private async selectChatModel(page: Page, model: string): Promise<void> {
    const menu = await this.firstVisible(page, this.definition.modelMenuSelectors, 2_000);
    if (!menu) throw new AdapterError("MODEL_MENU_NOT_FOUND", "ChatGPT 模型菜单不可用", true);
    await menu.click();
    for (const selector of this.definition.modelOptionSelectors) {
      const options = page.locator(selector).filter({ hasText: model });
      if (await options.count()) {
        await options.first().click();
        await page.waitForTimeout(150);
        return;
      }
    }
    await page.keyboard.press("Escape").catch(() => undefined);
    throw new AdapterError("MODEL_UNAVAILABLE", `ChatGPT 当前账号没有模型：${model}`, false);
  }

  private async stopCurrentGeneration(page: Page): Promise<void> {
    const stop = await this.firstVisible(page, this.definition.stopSelectors, 1_000);
    if (stop) await stop.click().catch(() => undefined);
  }

  private async applyExecutionMode(page: Page, mode: ResolvedExecutionMode): Promise<void> {
    if (mode === "current") return;
    const selectors =
      mode === "fast"
        ? this.definition.fastModeSelectors
        : this.definition.qualityModeSelectors;
    if (selectors.length === 0) return;
    let control = await this.firstVisible(page, selectors, 300);
    if (!control && this.definition.modeMenuSelectors.length > 0) {
      const menu = await this.firstVisible(page, this.definition.modeMenuSelectors, 1_000);
      if (menu) {
        await menu.click();
        await page.waitForTimeout(100);
        control = await this.firstVisible(page, selectors, 1_000);
      }
    }
    if (!control) return;
    const checked = await control.getAttribute("aria-checked").catch(() => null);
    if (checked !== "true") {
      await control.click();
      await page.waitForTimeout(150);
    }
  }

  private async disableUnneededFeatures(page: Page): Promise<void> {
    for (const selector of this.definition.disableFeatureSelectors) {
      const control = await this.firstVisible(page, [selector], 500);
      if (!control) continue;
      const toggle = control.locator(
        "xpath=ancestor-or-self::*[contains(concat(' ', normalize-space(@class), ' '), ' ds-toggle-button ')][1]",
      );
      const target = (await toggle.count()) > 0 ? toggle : control;
      const selected = await target.evaluate((element) =>
        element.getAttribute("aria-pressed") === "true" ||
        element.getAttribute("aria-checked") === "true" ||
        element.className.toString().includes("selected"),
      );
      if (selected) {
        await target.click();
        await page.waitForTimeout(100);
      }
    }
  }

  async cleanupCurrentConversation(): Promise<void> {
    if (this.page && !this.page.isClosed()) {
      await this.deleteCurrentConversation(this.page);
    }
  }

  private async startIndependentConversation(page: Page, timeoutMs: number): Promise<void> {
    // Always return to the provider home before a new task.  Reusing the
    // current conversation contaminates a chained workflow: e.g. a ledger
    // extraction answer can be mistaken for the next prose/revision answer.
    await page.goto(this.definition.homeUrl, { waitUntil: "domcontentloaded", timeout: timeoutMs });
    await page.waitForTimeout(this.id === "chatgpt" ? 750 : 350);
    if (this.id === "chatgpt") return;
    const newChat = await this.firstVisible(page, this.definition.newConversationSelectors, 2_000);
    if (newChat) {
      await newChat.click();
      await page.waitForTimeout(500);
    } else if (page.url() !== this.definition.homeUrl) {
      await page.goto(this.definition.homeUrl, { waitUntil: "domcontentloaded", timeout: timeoutMs });
    }
  }

  private async ensureAuthenticated(page: Page): Promise<void> {
    const issue = await this.authenticationIssue(page);
    if (!issue) return;
    throw new AdapterError(
      issue.state === "verification_required" ? "HUMAN_VERIFICATION_REQUIRED" : "AUTH_REQUIRED",
      issue.reason ?? `${this.definition.label} 尚未登录`,
      false,
    );
  }

  private async authenticationIssue(page: Page): Promise<Pick<BrowserProviderProbe, "state" | "reason"> | null> {
    const title = await page.title().catch(() => "");
    const body = await page.locator("body").innerText({ timeout: 2_000 }).catch(() => "");
    const url = page.url().toLowerCase();
    const loginVisible = await this.firstVisible(page, this.definition.loginIndicators, 250);
    const credentialInput = await this.firstVisible(page, [
      'input[type="password"]',
      'input[placeholder*="手机号"]',
      'input[placeholder*="邮箱"]',
      'input[name="email"]',
    ], 250);
    return classifyAuthenticationState(
      this.definition.label, title, body, url, Boolean(loginVisible), Boolean(credentialInput),
    );
  }

  private async findEditableInput(page: Page, timeoutMs: number): Promise<Locator | null> {
    return findEditableLocator(page, this.definition.inputSelectors, timeoutMs);
  }

  private async fillPrompt(page: Page, prompt: string, timeoutMs: number): Promise<Locator> {
    // A loaded chat page should expose its editor quickly. Waiting the entire
    // generation budget here hides account restrictions and provider errors
    // for up to twelve minutes before the user gets any feedback.
    return fillStablePrompt(
      page,
      this.definition.inputSelectors,
      prompt,
      Math.min(timeoutMs, 20_000),
      this.definition.label,
    );
  }

  private async firstVisible(
    page: Page,
    selectors: string[],
    timeoutMs: number,
  ): Promise<Locator | null> {
    const deadline = Date.now() + timeoutMs;
    do {
      for (const selector of selectors) {
        const matches = page.locator(selector);
        const count = Math.min(await matches.count().catch(() => 0), 20);
        for (let index = 0; index < count; index += 1) {
          const locator = matches.nth(index);
          if (await locator.isVisible().catch(() => false)) return locator;
        }
      }
      await page.waitForTimeout(200);
    } while (Date.now() < deadline);
    return null;
  }

  private async collectAssistantTexts(page: Page): Promise<string[]> {
    if (this.id === "deepseek") {
      return (await this.collectDeepSeekAssistantParts(page)).answer;
    }
    const texts: string[] = [];
    for (const selector of this.definition.assistantSelectors) {
      const values = await page.locator(selector).allInnerTexts().catch(() => []);
      texts.push(...values.filter(Boolean));
    }
    // The same assistant turn can match several compatibility selectors.
    // De-duplicate exact text so the baseline count cannot drift and make an
    // old answer look like a newly generated turn.
    return [...new Set(texts.map((text) => text.trim()).filter(Boolean))];
  }

  private async collectDeepSeekAssistantParts(page: Page): Promise<{ reasoning: string[]; answer: string[] }> {
    const nodes = await page.locator(".ds-markdown").evaluateAll((elements) => elements.map((element) => {
      const classNames: string[] = [];
      let current: Element | null = element;
      for (let depth = 0; current && depth < 6; depth += 1, current = current.parentElement) {
        if (typeof current.className === "string") classNames.push(current.className);
      }
      // innerText preserves the visual line breaks between paragraphs. Using
      // textContent flattens DeepSeek's nested <p>/<div> nodes into one line.
      const text = element instanceof HTMLElement
        ? element.innerText
        : element.textContent ?? "";
      return { text, classNames };
    })).catch(() => []);
    return splitDeepSeekDomCandidates(nodes);
  }

  private async waitForResponse(
    page: Page,
    expectedEnvelopeCount: number,
    baselineAssistantFingerprints: Set<string>,
    timeoutMs: number,
  ): Promise<void> {
    const budget = resolveGenerationWaitBudget(timeoutMs);
    const softDeadline = Date.now() + budget.softMs;
    const hardDeadline = Date.now() + budget.hardMs;
    let lastCandidate = "";
    let lastReasoning = "";
    let stableSince = Date.now();
    let lastProgressAt = Date.now();

    while (true) {
      const now = Date.now();
      const health = await this.assessPageGenerationHealth(page);
      if (!health.pageAlive) {
        throw new AdapterError("BROWSER_INTERRUPTED", `${this.definition.label} 页面已关闭或浏览器中断`, true);
      }
      if (health.interrupted) {
        throw new AdapterError(
          health.interruptCode ?? "BROWSER_INTERRUPTED",
          health.interruptReason ?? `${this.definition.label} 页面异常，无法继续等待模型回复`,
          health.retryable ?? false,
        );
      }

      const bodyText = await page.locator("body").innerText().catch(() => "");
      const envelopeCount = this.countOccurrences(bodyText, JSON_CLOSE);
      if (envelopeCount >= expectedEnvelopeCount) return;

      let contentProgressed = false;
      if (this.id === "deepseek") {
        const parts = await this.collectDeepSeekAssistantParts(page);
        const reasoning = selectLongestResponseCandidate(parts.reasoning);
        if (reasoning && reasoning !== lastReasoning) {
          lastReasoning = reasoning;
          contentProgressed = true;
          lastProgressAt = now;
        }
      }

      const assistantTexts = await this.collectAssistantTexts(page);
      const newCandidates = assistantTexts.filter(
        (text) => !baselineAssistantFingerprints.has(answerFingerprint(text)),
      );
      if (newCandidates.length > 0) {
        // DeepSeek's DOM may expose a short nested JSON node (for example only
        // {"title":"..."}) while the parent answer is still streaming. Never
        // accept that transient parseable object immediately: track the longest
        // answer node and require it to be stable after generation becomes idle.
        const candidate = selectLongestResponseCandidate(newCandidates);
        if (candidate !== lastCandidate) {
          lastCandidate = candidate;
          stableSince = now;
          contentProgressed = true;
          lastProgressAt = now;
        } else if (
          candidate.length > 0 &&
          now - stableSince >= 2_500 &&
          await this.isGenerationIdle(page) &&
          (this.isCompleteJsonText(candidate) || candidate.length >= 1400)
        ) {
          // DeepSeek can stop at its output-token limit after producing the full
          // prose but before the final JSON quote/braces. A stable, idle answer
          // is safe to hand to the repair parser instead of waiting five minutes.
          return;
        }
      }

      const generating = !(await this.isGenerationIdle(page));
      const keepWaiting = shouldContinueHealthyWait({
        now,
        softDeadline,
        hardDeadline,
        pageAlive: health.pageAlive,
        interrupted: health.interrupted,
        generating,
        contentProgressed,
        lastProgressAt,
      });
      if (!keepWaiting) break;
      await page.waitForTimeout(120);
    }
    throw new AdapterError(
      "GENERATION_TIMEOUT",
      `${this.definition.label} 在 ${budget.hardMs}ms 内没有完成 JSON 回复` +
        (Date.now() > softDeadline ? "（含健康延长等待）" : ""),
      true,
    );
  }

  private async assessPageGenerationHealth(page: Page): Promise<{
    pageAlive: boolean;
    interrupted: boolean;
    interruptCode?: string;
    interruptReason?: string;
    retryable?: boolean;
  }> {
    if (page.isClosed()) {
      return {
        pageAlive: false,
        interrupted: true,
        interruptCode: "BROWSER_INTERRUPTED",
        interruptReason: `${this.definition.label} 页面已关闭`,
        retryable: true,
      };
    }
    const auth = await this.authenticationIssue(page).catch(() => null);
    if (auth) {
      return {
        pageAlive: true,
        interrupted: true,
        interruptCode: auth.state === "verification_required" ? "HUMAN_VERIFICATION_REQUIRED" : "AUTH_REQUIRED",
        interruptReason: auth.reason ?? `${this.definition.label} 登录/验证状态异常`,
        retryable: false,
      };
    }
    return { pageAlive: true, interrupted: false };
  }

  private async isGenerationIdle(page: Page): Promise<boolean> {
    for (const selector of this.definition.stopSelectors) {
      if (await page.locator(selector).first().isVisible().catch(() => false)) return false;
    }
    const input = await this.firstVisible(page, this.definition.inputSelectors, 100);
    return Boolean(input && await input.isEnabled().catch(() => false));
  }

  private isCompleteJsonText(text: string): boolean {
    try {
      parseJsonText(extractJsonText(text));
      return true;
    } catch {
      return false;
    }
  }

  private countOccurrences(text: string, token: string): number {
    if (!token) return 0;
    let count = 0;
    let offset = 0;
    while ((offset = text.indexOf(token, offset)) >= 0) {
      count += 1;
      offset += token.length;
    }
    return count;
  }

  private async extractFinalAnswer(page: Page): Promise<string> {
    const texts = await this.collectAssistantTexts(page);
    const marked = [...texts].reverse().find((text) => text.includes(JSON_OPEN));
    if (marked) return marked;
    const bareJson = [...texts].reverse().find((text) => this.isCompleteJsonText(text));
    if (bareJson) return bareJson;
    const truncatedJson = [...texts].reverse().find((text) => text.includes("{") && /["']?content["']?\s*:/.test(text));
    if (truncatedJson) return truncatedJson;

    // Do not parse the whole page: it contains the user's prompt and therefore
    // our envelope example. On a provider/network error that prompt can look
    // like a valid answer even though the assistant produced no output.
    throw new AdapterError("EMPTY_MODEL_RESPONSE", "没有找到模型最终回复", true);
  }

  private extractConversationId(url: string): string | null {
    const marker = this.definition.conversationUrlPattern;
    if (!marker) return null;
    const index = url.indexOf(marker);
    if (index < 0) return null;
    return url.slice(index + marker.length).split(/[/?#]/)[0] || null;
  }

  private async collectConversationIds(page: Page): Promise<string[]> {
    const marker = this.definition.conversationUrlPattern;
    if (!marker) return [];
    const hrefs = await page.locator(`a[href*="${marker}"]`).evaluateAll((elements) =>
      elements
        .map((element) => element.getAttribute("href"))
        .filter((href): href is string => Boolean(href)),
    );
    return hrefs
      .map((href) => this.extractConversationId(href))
      .filter((id): id is string => Boolean(id));
  }

  private async findNewConversationId(
    page: Page,
    conversationIdsBefore: string[],
  ): Promise<string | null> {
    const previous = new Set(conversationIdsBefore);
    for (let attempt = 0; attempt < 8; attempt += 1) {
      const current = await this.collectConversationIds(page);
      const added = current.find((id) => !previous.has(id));
      if (added) return added;
      await page.waitForTimeout(250);
    }
    return this.extractConversationId(page.url());
  }

  private async deleteCurrentConversation(page: Page): Promise<void> {
    const menu = await this.firstVisible(page, this.definition.deleteMenuSelectors, 2_000);
    if (!menu) return;
    await menu.click();
    const action = await this.firstVisible(page, this.definition.deleteActionSelectors, 2_000);
    if (!action) return;
    await action.click();
    const confirm = await this.firstVisible(page, this.definition.deleteConfirmSelectors, 2_000);
    if (confirm) await confirm.click();
  }
}
