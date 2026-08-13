(() => {
  "use strict";

  const contract = globalThis.MaliangWebAIContract;
  if (!contract) throw new Error("Maliang web AI contract was not loaded");

  class WebAIError extends Error {
    constructor(code, message, retryable = false) {
      super(message);
      this.code = code;
      this.retryable = retryable;
    }
  }

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const LEDGER_KEY = "webAiExecutionLedgers";
  const RECOVERY_RETENTION_MS = 72 * 60 * 60 * 1_000;
  const CONFIRMED_ERROR_MS = 10_000;
  const UNKNOWN_IDLE_MS = 30_000;
  const PROGRESS_INTERVAL_MS = 12_000;

  function definitionForPage() {
    return Object.values(contract.providers).find((item) => item.hosts.includes(location.hostname)) || null;
  }

  function visible(element) {
    if (!element) return false;
    const style = getComputedStyle(element);
    const box = element.getBoundingClientRect();
    return style.visibility !== "hidden" && style.display !== "none" && box.width > 0 && box.height > 0;
  }

  function firstVisible(selectors) {
    for (const selector of selectors || []) {
      for (const element of document.querySelectorAll(selector)) {
        if (visible(element)) return element;
      }
    }
    return null;
  }

  function pageHasText(values) {
    const text = (document.body?.innerText || "").slice(0, 100_000);
    return (values || []).some((value) => text.includes(value));
  }

  async function waitForInput(definition, timeoutMs = 15_000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const input = firstVisible(definition.inputSelectors);
      if (input) return input;
      await sleep(200);
    }
    return null;
  }

  function inputEnabled(input) {
    return !input.disabled && input.getAttribute("aria-disabled") !== "true";
  }

  function controlEnabled(control) {
    return Boolean(control)
      && !control.disabled
      && control.getAttribute("aria-disabled") !== "true";
  }

  async function waitForSendControl(definition, timeoutMs = 5_000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const control = firstVisible(definition.sendSelectors);
      if (controlEnabled(control)) return control;
      await sleep(100);
    }
    return null;
  }

  function pressEnter(input) {
    input.focus();
    for (const type of ["keydown", "keypress", "keyup"]) {
      input.dispatchEvent(new KeyboardEvent(type, {
        key: "Enter",
        code: "Enter",
        keyCode: 13,
        which: 13,
        bubbles: true,
        cancelable: true,
      }));
    }
  }

  async function submitPrompt(definition, input, sendTimeoutMs = 5_000) {
    const send = await waitForSendControl(definition, sendTimeoutMs);
    if (send) {
      send.click();
      return "button";
    }

    // Chat pages commonly support Enter even when the submit control is
    // rendered as an icon-only div or is replaced during a React update.
    pressEnter(input);
    return "enter";
  }

  function fillInput(input, prompt) {
    input.focus();
    if (input instanceof HTMLTextAreaElement || input instanceof HTMLInputElement) {
      const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
      if (setter) setter.call(input, prompt);
      else input.value = prompt;
    } else {
      const selection = getSelection();
      const range = document.createRange();
      range.selectNodeContents(input);
      selection.removeAllRanges();
      selection.addRange(range);
      document.execCommand("insertText", false, prompt);
      selection.removeAllRanges();
    }
    input.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: prompt }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function assistantTexts(definition) {
    const values = [];
    for (const selector of definition.assistantSelectors) {
      for (const element of document.querySelectorAll(selector)) {
        const text = (element.innerText || element.textContent || "").trim();
        if (text) values.push(text);
      }
    }
    return [...new Set(values)];
  }

  function assistantParts(definition) {
    if (definition.id !== "deepseek") return { reasoning: [], answer: assistantTexts(definition) };
    const reasoning = [];
    const answer = [];
    const containerAnswers = [];
    for (const selector of definition.answerContainerSelectors || []) {
      for (const element of document.querySelectorAll(selector)) {
        const text = (element.innerText || element.textContent || "").trim();
        if (text) containerAnswers.push(text);
      }
    }
    for (const element of document.querySelectorAll(".ds-markdown")) {
      const text = (element.innerText || element.textContent || "").trim();
      if (!text) continue;
      let current = element;
      let isReasoning = false;
      let isAnswer = false;
      for (let depth = 0; current && depth < 6; depth += 1, current = current.parentElement) {
        const classes = typeof current.className === "string" ? current.className.split(/\s+/) : [];
        if (classes.includes("ds-think-content")) isReasoning = true;
        if (classes.includes("ds-assistant-message-main-content")) isAnswer = true;
      }
      if (isReasoning) reasoning.push(text);
      else if (isAnswer) answer.push(text);
    }
    return {
      reasoning: [...new Set(reasoning)],
      answer: containerAnswers.length
        ? [...new Set(containerAnswers)]
        : answer.length ? [...new Set(answer)] : assistantTexts(definition),
    };
  }

  function longest(values) {
    return values.reduce((best, value) => value.length > best.length ? value : best, "");
  }

  function isInstructionalPlaceholder(value) {
    const trimmed = String(value || "").trim();
    if (!trimmed) return true;
    const compact = trimmed.replace(/\s+/g, " ").toLowerCase();
    return compact === "合法json"
      || compact === "合法 json"
      || compact === "json"
      || compact === "..."
      || compact === "{...}"
      || compact === "[...]"
      || (trimmed.length <= 32 && !/^[\[{]/.test(trimmed));
  }

  function repairJsonText(candidate) {
    const source = String(candidate || "").replace(/^\uFEFF/, "").replace(/[\u200B-\u200D\u2060]/g, "");
    let repaired = "";
    let inString = false;
    let escaped = false;
    for (const char of source) {
      if (inString) {
        if (escaped) {
          repaired += char;
          escaped = false;
        } else if (char === "\\") {
          repaired += char;
          escaped = true;
        } else if (char === '"') {
          repaired += char;
          inString = false;
        } else if (char === "\n") repaired += "\\n";
        else if (char === "\r") repaired += "\\r";
        else if (char === "\t") repaired += "\\t";
        else repaired += char;
      } else {
        repaired += char;
        if (char === '"') inString = true;
      }
    }
    return repaired.replace(/,\s*([}\]])/g, "$1");
  }

  function tryParseObject(candidate) {
    if (!candidate || isInstructionalPlaceholder(candidate)) return null;
    const start = candidate.indexOf("{");
    const end = candidate.lastIndexOf("}");
    const objectSlice = start >= 0 && end > start ? candidate.slice(start, end + 1) : "";
    const variants = [candidate, objectSlice, repairJsonText(candidate), repairJsonText(objectSlice)];
    for (const variant of [...new Set(variants)].filter(Boolean)) {
      try {
        const value = JSON.parse(variant);
        if (value !== null && typeof value === "object") return value;
      } catch (_) { /* not structured */ }
    }
    return null;
  }

  function extractStructured(text) {
    const open = "<MODEL_JSON>";
    const close = "</MODEL_JSON>";
    const source = String(text || "");

    // Walk marked envelopes from the end; skip instructional placeholders such
    // as prompt text "<MODEL_JSON>合法JSON</MODEL_JSON>" so bare model JSON wins.
    let searchFrom = source.length;
    while (searchFrom > 0) {
      const closeIndex = source.lastIndexOf(close, searchFrom - 1);
      if (closeIndex < 0) break;
      const openIndex = source.lastIndexOf(open, closeIndex);
      if (openIndex < 0) {
        searchFrom = closeIndex;
        continue;
      }
      const body = source.slice(openIndex + open.length, closeIndex).trim();
      const parsed = tryParseObject(body);
      if (parsed) return parsed;
      searchFrom = openIndex;
    }

    const fenced = [...source.matchAll(/```(?:json)?\s*([\s\S]*?)```/gi)];
    for (let i = fenced.length - 1; i >= 0; i -= 1) {
      const parsed = tryParseObject((fenced[i][1] || "").trim());
      if (parsed) return parsed;
    }

    // Bare object in the full answer (common when model ignores envelope tags).
    return tryParseObject(source);
  }

  function requiresStructuredOutput(payload) {
    if (payload?.operation === "json_generation") return true;
    const schema = payload?.json_schema;
    return Boolean(schema && typeof schema === "object" && Object.keys(schema).length > 0);
  }

  function compilePrompt(payload) {
    const prompt = String(payload?.prompt || "").trim();
    if (!requiresStructuredOutput(payload)) return prompt;
    const schema = payload.json_schema && typeof payload.json_schema === "object"
      ? payload.json_schema
      : { type: "object", additionalProperties: true };
    return [
      prompt,
      "\n【结构化输出协议（优先级最高）】",
      `输出必须符合以下 JSON Schema：${JSON.stringify(schema)}`,
      "只返回一个 JSON 对象，并用 <MODEL_JSON> 与 </MODEL_JSON> 完整包裹。",
      "不要返回 Markdown 代码块、解释、注释、思考过程或 JSON 之外的文字。",
      "即使前面的任务描述要求其他输出格式，也必须以本结构化输出协议为准。",
    ].join("\n");
  }

  function normalizeFingerprintText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  async function sha256(value) {
    const bytes = new TextEncoder().encode(String(value || ""));
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  async function answerFingerprint(value) {
    return sha256(normalizeFingerprintText(value).slice(0, 20_000));
  }

  async function readLedger(provider) {
    const stored = await chrome.storage.local.get(LEDGER_KEY);
    const ledger = stored[LEDGER_KEY]?.[provider] || null;
    if (!ledger) return null;
    const lastActivity = Date.parse(ledger.last_progress_at || ledger.updated_at || "");
    if (Number.isFinite(lastActivity) && Date.now() - lastActivity > RECOVERY_RETENTION_MS) {
      await clearLedger(provider);
      return null;
    }
    return ledger;
  }

  async function writeLedger(provider, patch) {
    const stored = await chrome.storage.local.get(LEDGER_KEY);
    const ledgers = { ...(stored[LEDGER_KEY] || {}) };
    ledgers[provider] = { ...(ledgers[provider] || {}), ...patch, updated_at: new Date().toISOString() };
    await chrome.storage.local.set({ [LEDGER_KEY]: ledgers });
    return ledgers[provider];
  }

  async function clearLedger(provider) {
    const stored = await chrome.storage.local.get(LEDGER_KEY);
    const ledgers = { ...(stored[LEDGER_KEY] || {}) };
    delete ledgers[provider];
    await chrome.storage.local.set({ [LEDGER_KEY]: ledgers });
  }

  async function rejectLedgerAnswer(provider, rawText) {
    const ledger = await readLedger(provider);
    if (!ledger || !rawText) return;
    const rejected = new Set(ledger.rejected_answer_fingerprints || []);
    rejected.add(await answerFingerprint(rawText));
    await writeLedger(provider, {
      ...ledger,
      phase: "preparing",
      rejected_answer_fingerprints: [...rejected].slice(-40),
    });
  }

  function sameExecution(ledger, payload, promptFingerprint) {
    return Boolean(
      ledger
      && ledger.provider === payload.provider
      && ledger.idempotency_key === payload.idempotency_key
      && ledger.prompt_fingerprint === promptFingerprint
    );
  }

  function visibleErrorText(definition) {
    for (const element of document.querySelectorAll('[role="alert"],[data-testid*="error" i],[class*="error" i],button')) {
      if (!visible(element)) continue;
      const text = (element.innerText || element.textContent || "").trim();
      if (!text || text.length > 500) continue;
      const matched = (definition.errorTexts || []).find((value) => text.includes(value));
      if (matched) return matched;
    }
    return "";
  }

  function pageHealth(definition) {
    if (!document.body) return { state: "unavailable", reason: "页面内容不可用" };
    if (pageHasText(definition.verificationTexts)) return { state: "verification_required", reason: "需要人工验证" };
    if (firstVisible(definition.loginSelectors)) return { state: "login_required", reason: "登录状态失效" };
    const error = visibleErrorText(definition);
    if (error) return { state: "platform_error", reason: error };
    return { state: "healthy", reason: "" };
  }

  function visibleGenerationText(definition) {
    const values = definition.generatingTexts || [];
    if (!values.length) return "";
    for (const element of document.querySelectorAll('button,[role="button"],[role="status"],[aria-live],[aria-busy="true"]')) {
      if (!visible(element)) continue;
      const text = [
        element.innerText,
        element.textContent,
        element.getAttribute?.("aria-label"),
        element.getAttribute?.("title"),
      ].filter(Boolean).join(" ").trim();
      const matched = values.find((value) => text.includes(value));
      if (matched) return matched;
    }
    return "";
  }

  function generationEvidence(definition, input, progressChanged = false) {
    if (progressChanged) return true;
    if (firstVisible(definition.stopSelectors)) return true;
    if (firstVisible(definition.generatingSelectors)) return true;
    if (visibleGenerationText(definition)) return true;
    return Boolean(input && !inputEnabled(input));
  }

  function decideWaitState({ healthState, generating, valid, stableForMs, abnormalForMs, unknownForMs }) {
    if (valid && !generating && stableForMs >= 1_800) return "completed";
    if (healthState !== "healthy" && abnormalForMs >= CONFIRMED_ERROR_MS) return valid ? "completed" : "confirmed_error";
    if (healthState === "healthy" && !generating && !valid && unknownForMs >= UNKNOWN_IDLE_MS) return "unknown_idle";
    return "continue";
  }

  function clickNewConversation(definition) {
    return clickText(definition.newConversationTexts || []);
  }

  async function navigateForFreshConversation(definition, provider, ledger) {
    if (location.href === definition.homeUrl || clickNewConversation(definition)) return;
    await writeLedger(provider, { ...ledger, phase: "preparing", conversation_url: definition.homeUrl });
    location.replace(definition.homeUrl);
    throw new WebAIError("NAVIGATION_PENDING", `${definition.label} 正在打开新会话`, true);
  }

  function clickText(values) {
    for (const element of document.querySelectorAll('button,[role="button"],[role="radio"],label')) {
      if (!visible(element)) continue;
      const text = (element.innerText || element.textContent || "").trim();
      if (values.some((value) => text.includes(value))) {
        element.click();
        return true;
      }
    }
    return false;
  }

  async function probe() {
    const definition = definitionForPage();
    if (!definition) return { supported: false, authenticated: false, ready: false, reason: "unsupported page" };
    if (pageHasText(definition.verificationTexts)) {
      return { provider: definition.id, supported: true, authenticated: false, ready: false, state: "verification_required" };
    }
    const loginVisible = Boolean(firstVisible(definition.loginSelectors));
    const input = await waitForInput(definition, 1_000);
    const authenticated = Boolean(input) && !loginVisible;
    return {
      provider: definition.id,
      supported: true,
      authenticated,
      ready: authenticated && inputEnabled(input),
      state: authenticated ? "ready" : "login_required",
      url: location.href,
    };
  }

  async function assertReady(definition) {
    const state = await probe();
    if (state.state === "verification_required") {
      throw new WebAIError("HUMAN_VERIFICATION_REQUIRED", `${definition.label} 需要人工完成安全验证`);
    }
    if (!state.authenticated) throw new WebAIError("AUTH_REQUIRED", `${definition.label} 尚未登录`);
    const input = await waitForInput(definition);
    if (!input) throw new WebAIError("ADAPTER_OUTDATED", `${definition.label} 输入框未找到`, true);
    return input;
  }

  async function waitForAnswer(definition, baselineCount, options = {}) {
    let latest = "";
    let latestReasoning = "";
    let stableSince = Date.now();
    let abnormalSince = 0;
    let unknownSince = 0;
    let lastProgressSentAt = 0;
    let lastActivityAt = options.assumeGenerating ? Date.now() : 0;
    while (true) {
      const now = Date.now();
      const health = pageHealth(definition);
      const parts = assistantParts(definition);
      const reasoning = longest(parts.reasoning);
      const values = parts.answer.slice(baselineCount);
      const candidate = longest(values);
      const answerChanged = Boolean(candidate && candidate !== latest);
      const reasoningChanged = Boolean(reasoning && reasoning !== latestReasoning);
      if (answerChanged) {
        latest = candidate;
        stableSince = now;
        unknownSince = 0;
      }
      if (reasoningChanged) {
        latestReasoning = reasoning;
        unknownSince = 0;
      }
      const input = firstVisible(definition.inputSelectors);
      const explicitGenerating = generationEvidence(definition, input, answerChanged || reasoningChanged);
      if (explicitGenerating) lastActivityAt = now;
      const generating = explicitGenerating || Boolean(lastActivityAt && now - lastActivityAt < 2_500);
      const idleControl = firstVisible(definition.idleSelectors || definition.sendSelectors);
      const idle = !generating && Boolean(input && inputEnabled(input) && controlEnabled(idleControl));
      const valid = latest && (!options.structured || Boolean(extractStructured(latest)));
      if (valid && idle && decideWaitState({
        healthState: health.state, generating, valid: true, stableForMs: now - stableSince,
        abnormalForMs: abnormalSince ? now - abnormalSince : 0, unknownForMs: 0,
      }) === "completed") return latest;
      const completeStructuredEnvelope = Boolean(
        options.structured && latest.includes("</MODEL_JSON>") && now - stableSince >= 5_000
      );
      if (completeStructuredEnvelope && !generating) return latest;

      if (health.state !== "healthy") {
        abnormalSince ||= now;
        if (decideWaitState({
          healthState: health.state, generating, valid, stableForMs: now - stableSince,
          abnormalForMs: now - abnormalSince, unknownForMs: 0,
        }) !== "continue") {
          if (valid && idle) return latest;
          const code = health.state === "verification_required" ? "HUMAN_VERIFICATION_REQUIRED"
            : health.state === "login_required" ? "AUTH_REQUIRED" : "PAGE_EXECUTION_ERROR";
          throw new WebAIError(code, `${definition.label} 页面异常：${health.reason}`, code === "PAGE_EXECUTION_ERROR");
        }
      } else {
        abnormalSince = 0;
      }

      if (health.state === "healthy" && idle && !valid) {
        unknownSince ||= now;
        if (decideWaitState({
          healthState: health.state, generating, valid, stableForMs: now - stableSince,
          abnormalForMs: 0, unknownForMs: now - unknownSince,
        }) === "unknown_idle") {
          if (valid) return latest;
          throw new WebAIError("GENERATION_STALLED", `${definition.label} 已停止生成但没有可用回复`, true);
        }
      } else {
        unknownSince = 0;
      }

      const phase = generating
        ? (latest ? "generating" : latestReasoning ? "thinking" : "submitted")
        : latest ? "stabilizing" : "submitted";
      if (options.onProgress && (now - lastProgressSentAt >= PROGRESS_INTERVAL_MS || options.lastPhase !== phase)) {
        lastProgressSentAt = now;
        options.lastPhase = phase;
        const response = await options.onProgress({
          phase,
          generating,
          page_health: health.state,
          answer_length: latest.length,
          reasoning_length: latestReasoning.length,
          conversation_url: location.href,
          last_progress_at: new Date(now).toISOString(),
        });
        if (response?.cancel_requested) {
          const stop = firstVisible(definition.stopSelectors);
          if (stop) stop.click();
          throw new WebAIError("CANCELLED", "任务已取消");
        }
      }
      await sleep(200);
    }
  }

  async function execute(job, runtime = {}) {
    const definition = definitionForPage();
    const payload = job.payload || {};
    if (!definition || definition.id !== payload.provider) {
      throw new WebAIError("ADAPTER_OUTDATED", "浏览器 AI 任务与当前网页不匹配", true);
    }
    const startedAt = Date.now();
    const compiledPrompt = compilePrompt(payload);
    const promptFingerprint = await sha256(compiledPrompt);
    let ledger = await readLedger(definition.id);
    const recoverable = sameExecution(ledger, payload, promptFingerprint);
    if (!recoverable) {
      ledger = await writeLedger(definition.id, {
        task_id: job.id,
        idempotency_key: payload.idempotency_key,
        provider: definition.id,
        prompt_fingerprint: promptFingerprint,
        conversation_url: location.href,
        phase: "preparing",
        last_progress_at: new Date().toISOString(),
        last_answer_fingerprint: "",
        rejected_answer_fingerprints: [],
      });
    }

    const onProgress = async (progress) => {
      ledger = await writeLedger(definition.id, {
        ...ledger,
        task_id: job.id,
        ...progress,
      });
      return runtime.onProgress?.({ ...progress, prompt_fingerprint: promptFingerprint });
    };

    if (recoverable) {
      const existing = longest(assistantParts(definition).answer);
      const existingFingerprint = existing ? await answerFingerprint(existing) : "";
      const rejected = new Set(ledger.rejected_answer_fingerprints || []);
      const generating = Boolean(firstVisible(definition.stopSelectors));
      const phaseMayStillBeRunning = ["submitted", "thinking", "generating", "stabilizing"].includes(ledger.phase);
      if (generating || phaseMayStillBeRunning || (existing && !rejected.has(existingFingerprint))) {
        let outputText;
        let recoveryAbandoned = false;
        try {
          outputText = generating || phaseMayStillBeRunning
            ? await waitForAnswer(definition, 0, {
              structured: requiresStructuredOutput(payload), onProgress, assumeGenerating: true,
            })
            : existing;
        } catch (error) {
          if (!["GENERATION_STALLED", "PAGE_EXECUTION_ERROR"].includes(error.code)) throw error;
          const finalCandidate = longest(assistantParts(definition).answer);
          if (finalCandidate) rejected.add(await answerFingerprint(finalCandidate));
          ledger = await writeLedger(definition.id, {
            ...ledger, phase: "preparing", rejected_answer_fingerprints: [...rejected].slice(-40),
          });
          await navigateForFreshConversation(definition, definition.id, ledger);
          recoveryAbandoned = true;
          outputText = "";
        }
        const data = extractStructured(outputText);
        if (
          !recoveryAbandoned && requiresStructuredOutput(payload) && !data
          && outputText.includes("</MODEL_JSON>")
        ) {
          throw new WebAIError(
            "INVALID_MODEL_JSON_COMPLETE",
            `${definition.label} returned a complete but invalid JSON envelope; the conversation was preserved`,
            false,
          );
        }
        if (!recoveryAbandoned && (!requiresStructuredOutput(payload) || data)) {
          await writeLedger(definition.id, {
            ...ledger, phase: "completed", conversation_url: location.href,
            last_answer_fingerprint: await answerFingerprint(outputText), last_progress_at: new Date().toISOString(),
          });
          return {
            provider: definition.id, source: `${definition.id}_web_extension`, output_text: outputText, data,
            recovered: true, salvaged_after_interruption: !generating,
            prompt_fingerprint: promptFingerprint, conversation_url: location.href,
            execution_duration_ms: Date.now() - startedAt, last_progress_at: new Date().toISOString(),
            adapter_contract_version: contract.version,
          };
        }
        rejected.add(await answerFingerprint(outputText));
        ledger = await writeLedger(definition.id, { ...ledger, rejected_answer_fingerprints: [...rejected].slice(-40) });
      }
      await navigateForFreshConversation(definition, definition.id, ledger);
    }

    const input = await assertReady(definition);
    if (definition.id === "deepseek" && payload.mode === "fast") clickText(definition.fastModeTexts || []);
    if (definition.id === "deepseek" && payload.mode === "quality") clickText(definition.qualityModeTexts || []);
    const baselineCount = assistantParts(definition).answer.length;
    fillInput(input, compiledPrompt);
    await submitPrompt(definition, input);
    await onProgress({ phase: "submitted", generating: true, page_health: "healthy", answer_length: 0,
      reasoning_length: 0, conversation_url: location.href, last_progress_at: new Date().toISOString() });
    const outputText = await waitForAnswer(definition, baselineCount, {
      structured: requiresStructuredOutput(payload), onProgress, assumeGenerating: true,
    });
    const data = extractStructured(outputText);
    if (requiresStructuredOutput(payload) && !data && outputText.includes("</MODEL_JSON>")) {
      throw new WebAIError(
        "INVALID_MODEL_JSON_COMPLETE",
        `${definition.label} returned a complete but invalid JSON envelope; the conversation was preserved`,
        false,
      );
    }
    if (requiresStructuredOutput(payload) && !data) {
      throw new WebAIError("INVALID_MODEL_JSON", `${definition.label} 未返回可解析的 JSON 对象`, true);
    }
    return {
      provider: definition.id,
      source: `${definition.id}_web_extension`,
      output_text: outputText,
      data,
      recovered: false,
      salvaged_after_interruption: false,
      prompt_fingerprint: promptFingerprint,
      conversation_url: location.href,
      execution_duration_ms: Date.now() - startedAt,
      last_progress_at: new Date().toISOString(),
      adapter_contract_version: contract.version,
    };
  }

  globalThis.MaliangWebAIAdapter = Object.freeze({
    execute,
    probe,
    definitionForPage,
    compilePrompt,
    requiresStructuredOutput,
    sameExecution,
    pageHealth,
    generationEvidence,
    decideWaitState,
    clearLedger,
    rejectLedgerAnswer,
    waitForAnswer,
    submitPrompt,
    extractStructured,
    WebAIError,
  });
})();
