import assert from "node:assert/strict";
import { readFile, stat } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const root = new URL("../", import.meta.url);
const manifest = JSON.parse(await readFile(new URL("manifest.json", root), "utf8"));

test("manifest is MV3 and does not request cookies", () => {
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.permissions.includes("cookies"), false);
  assert.equal(manifest.permissions.includes("identity"), false);
  assert.equal(manifest.name, "青玉浏览器助手");
  assert.ok(manifest.host_permissions.includes("http://127.0.0.1:8000/*"));
  assert.equal(manifest.host_permissions.some((item) => item.includes("maliang.example.com")), false);
});

test("one extension declares Fanqie, ChatGPT, and DeepSeek capabilities", async () => {
  assert.ok(manifest.host_permissions.includes("https://fanqienovel.com/*"));
  assert.ok(manifest.host_permissions.includes("https://chatgpt.com/*"));
  assert.ok(manifest.host_permissions.includes("https://chat.deepseek.com/*"));
  const webAi = manifest.content_scripts.find((entry) => entry.matches.includes("https://chatgpt.com/*"));
  assert.deepEqual(webAi.js, [
    "content/web-ai-contract.js",
    "content/conversation-cleanup.js",
    "content/web-ai-adapter.js",
    "content/web-ai-executor.js",
  ]);

  const background = await readFile(new URL("background.js", root), "utf8");
  assert.match(background, /"fanqie_publish", "chatgpt_web", "deepseek_web"/);
  assert.match(background, /\/browser-extension\/jobs\/claim\?wait_seconds=25/);
  assert.match(background, /job\.kind === "browser_ai"/);
});

test("session cleanup accepts only a unique provider conversation URL", async () => {
  const source = await readFile(new URL("content/conversation-cleanup.js", root), "utf8");
  const context = { location: { href: "https://chatgpt.com/" }, URL };
  vm.runInNewContext(source, context);
  const parse = context.MaliangConversationCleanup.parseConversationUrl;
  const definition = { hosts: ["chatgpt.com"], conversationPathPattern: /^\/c\/[0-9a-z-]+/i };
  assert.equal(parse("https://chatgpt.com/c/task-session-123", definition).key, "/c/task-session-123");
  assert.equal(parse("https://chatgpt.com/", definition), null);
  assert.equal(parse("https://example.com/c/user-session-456", definition), null);
});

test("cleanup deletes only the committed task session and preserves it when identity is uncertain", async () => {
  const background = await readFile(new URL("background.js", root), "utf8");
  const cleanup = await readFile(new URL("content/conversation-cleanup.js", root), "utf8");
  const executor = await readFile(new URL("content/web-ai-executor.js", root), "utf8");
  assert.match(cleanup, /rowConversations\.length !== 1 \|\| rowConversations\[0\]\.key !== target\.key/);
  assert.match(cleanup, /if \(!await waitUntilGone/);
  assert.match(cleanup, /waitForDeleteTransition/);
  assert.match(cleanup, /if \(transition\.gone\) return/);
  assert.doesNotMatch(cleanup, /deleteAction\.click\(\);\s*await sleep\(150\)/);
  assert.match(cleanup, /status: "preserved"/);
  assert.doesNotMatch(cleanup, /selectOverflow|discoverConversations|conversationRetentionLimit/);
  assert.doesNotMatch(cleanup, /fetch\(|XMLHttpRequest|document\.cookie/);
  assert.match(executor, /holdClaimForCleanup: true/);
  assert.match(executor, /if \(!committed\?\.ok \|\| !committed\.data\?\.committed\)/);
  assert.ok(executor.indexOf("const committed") < executor.indexOf("await removeCommittedSession"));
  assert.match(executor, /LEASE_RENEWED/);
  assert.match(background, /message\.type === "WEB_AI_PAGE_CONTEXT"/);
  assert.match(background, /managedTabId === sender\.tab\.id/);
  assert.match(executor, /if \(!context\?\.data\?\.managed\)/);
  assert.match(background, /webAiSessionCleanupLock/);
  assert.match(background, /WEB_AI_SESSION_CLEANUP_FINISHED/);
  assert.match(background, /if \(holdForCleanup\) setTimeout\(claimLoop, 60_250\)/);
});

test("web AI runs in extension-owned tabs and uses DOM only", async () => {
  const background = await readFile(new URL("background.js", root), "utf8");
  const adapter = await readFile(new URL("content/web-ai-adapter.js", root), "utf8");
  const contract = await readFile(new URL("content/web-ai-contract.js", root), "utf8");
  assert.match(background, /managedAiTabs/);
  assert.match(background, /chrome\.tabs\.create\(\{ url, active: false \}\)/);
  assert.match(adapter, /MaliangWebAIContract/);
  assert.match(contract, /data-message-author-role/);
  assert.match(contract, /\.ds-markdown/);
  assert.doesNotMatch(adapter, /fetch\(|XMLHttpRequest|document\.cookie/);
});

test("structured web AI tasks compile schema into a highest-priority JSON protocol", async () => {
  const source = await readFile(new URL("content/web-ai-adapter.js", root), "utf8");
  const context = {
    MaliangWebAIContract: { providers: {} },
    location: { hostname: "chat.deepseek.com" },
    document: { querySelectorAll: () => [] },
    getComputedStyle: () => ({ visibility: "visible", display: "block" }),
    setTimeout,
  };
  vm.runInNewContext(source, context);
  const prompt = context.MaliangWebAIAdapter.compilePrompt({
    operation: "json_generation",
    prompt: "写一段解释并使用 Markdown。",
    json_schema: {
      type: "object",
      required: ["title"],
      properties: { title: { type: "string" } },
    },
  });
  assert.match(prompt, /^写一段解释并使用 Markdown。/);
  assert.match(prompt, /"required":\["title"\]/);
  assert.match(prompt, /<MODEL_JSON> 与 <\/MODEL_JSON>/);
  assert.match(prompt, /优先级最高/);
  assert.ok(prompt.lastIndexOf("结构化输出协议") > prompt.indexOf("写一段解释"));
});

test("plain text web AI tasks keep the original prompt unchanged", async () => {
  const source = await readFile(new URL("content/web-ai-adapter.js", root), "utf8");
  const context = {
    MaliangWebAIContract: { providers: {} },
    location: { hostname: "chatgpt.com" },
    document: { querySelectorAll: () => [] },
    getComputedStyle: () => ({ visibility: "visible", display: "block" }),
    setTimeout,
  };
  vm.runInNewContext(source, context);
  assert.equal(
    context.MaliangWebAIAdapter.compilePrompt({ operation: "text_generation", prompt: " 保留自然语言输出 " }),
    "保留自然语言输出",
  );
  assert.equal(context.MaliangWebAIAdapter.requiresStructuredOutput({ json_schema: {} }), false);
  assert.equal(context.MaliangWebAIAdapter.requiresStructuredOutput({ json_schema: { type: "object" } }), true);
});

test("web AI wait state has no hard timeout and uses 10/30 second watchdogs", async () => {
  const source = await readFile(new URL("content/web-ai-adapter.js", root), "utf8");
  const context = {
    MaliangWebAIContract: { providers: {} }, location: { hostname: "chatgpt.com" },
    document: { querySelectorAll: () => [] }, getComputedStyle: () => ({ visibility: "visible", display: "block" }),
    setTimeout,
  };
  vm.runInNewContext(source, context);
  const decide = context.MaliangWebAIAdapter.decideWaitState;
  assert.equal(decide({ healthState: "healthy", generating: true, valid: false,
    stableForMs: 999_999_999, abnormalForMs: 0, unknownForMs: 999_999_999 }), "continue");
  assert.equal(decide({ healthState: "platform_error", generating: false, valid: false,
    stableForMs: 0, abnormalForMs: 9_999, unknownForMs: 0 }), "continue");
  assert.equal(decide({ healthState: "platform_error", generating: false, valid: false,
    stableForMs: 0, abnormalForMs: 10_000, unknownForMs: 0 }), "confirmed_error");
  assert.equal(decide({ healthState: "healthy", generating: false, valid: false,
    stableForMs: 0, abnormalForMs: 0, unknownForMs: 30_000 }), "unknown_idle");
  assert.equal(decide({ healthState: "healthy", generating: false, valid: true,
    stableForMs: 1_800, abnormalForMs: 0, unknownForMs: 0 }), "completed");
});

test("web AI recovery identity requires provider, idempotency key, and prompt fingerprint", async () => {
  const source = await readFile(new URL("content/web-ai-adapter.js", root), "utf8");
  const context = {
    MaliangWebAIContract: { providers: {} }, location: { hostname: "chat.deepseek.com" },
    document: { querySelectorAll: () => [] }, getComputedStyle: () => ({ visibility: "visible", display: "block" }),
    setTimeout,
  };
  vm.runInNewContext(source, context);
  const same = context.MaliangWebAIAdapter.sameExecution;
  const ledger = { provider: "deepseek", idempotency_key: "idem-1", prompt_fingerprint: "hash-1" };
  assert.equal(same(ledger, { provider: "deepseek", idempotency_key: "idem-1" }, "hash-1"), true);
  assert.equal(same(ledger, { provider: "deepseek", idempotency_key: "idem-2" }, "hash-1"), false);
  assert.equal(same(ledger, { provider: "chatgpt", idempotency_key: "idem-1" }, "hash-1"), false);
  assert.equal(same(ledger, { provider: "deepseek", idempotency_key: "idem-1" }, "hash-2"), false);
});

test("backend-rejected structured answers are fingerprinted before a retry", async () => {
  const adapter = await readFile(new URL("content/web-ai-adapter.js", root), "utf8");
  const executor = await readFile(new URL("content/web-ai-executor.js", root), "utf8");
  const background = await readFile(new URL("background.js", root), "utf8");
  assert.match(adapter, /async function rejectLedgerAnswer/);
  assert.match(adapter, /rejected_answer_fingerprints/);
  assert.match(executor, /adapter\.rejectLedgerAnswer/);
  assert.ok(executor.indexOf("adapter.rejectLedgerAnswer") < executor.indexOf("任务结果尚未被系统确认"));
  assert.match(background, /result: completed\?\.result \|\| \{\}/);
});

test("web AI submission tolerates delayed and icon-only send controls", async () => {
  const adapter = await readFile(new URL("content/web-ai-adapter.js", root), "utf8");
  const contract = await readFile(new URL("content/web-ai-contract.js", root), "utf8");
  assert.match(adapter, /waitForSendControl\(definition, timeoutMs = 5_000\)/);
  assert.match(adapter, /await sleep\(100\)/);
  assert.match(adapter, /pressEnter\(input\)/);
  assert.doesNotMatch(adapter, /await sleep\(250\);\s*const send/);
  assert.match(contract, /composer-submit-button/);
  assert.match(contract, /\[role=\\?"button\\?"\]\[aria-label\*=/);
});

test("web AI waits for a delayed send control before clicking it", async () => {
  const source = await readFile(new URL("content/web-ai-adapter.js", root), "utf8");
  let queries = 0;
  let clicks = 0;
  const button = {
    disabled: false,
    getAttribute: () => null,
    getBoundingClientRect: () => ({ width: 36, height: 36 }),
    click: () => { clicks += 1; },
  };
  const context = {
    MaliangWebAIContract: { providers: {} },
    location: { hostname: "chat.deepseek.com" },
    document: {
      querySelectorAll: () => (++queries >= 3 ? [button] : []),
    },
    getComputedStyle: () => ({ visibility: "visible", display: "block" }),
    setTimeout,
    KeyboardEvent: class {
      constructor(type) { this.type = type; }
    },
  };
  vm.runInNewContext(source, context);
  const result = await context.MaliangWebAIAdapter.submitPrompt(
    { sendSelectors: ["button"] },
    { focus() {}, dispatchEvent() {} },
    1_000,
  );
  assert.equal(result, "button");
  assert.equal(clicks, 1);
  assert.ok(queries >= 3);
});

test("web AI falls back to Enter when a site has no addressable send control", async () => {
  const source = await readFile(new URL("content/web-ai-adapter.js", root), "utf8");
  const events = [];
  const context = {
    MaliangWebAIContract: { providers: {} },
    location: { hostname: "chat.deepseek.com" },
    document: { querySelectorAll: () => [] },
    getComputedStyle: () => ({ visibility: "visible", display: "block" }),
    setTimeout,
    KeyboardEvent: class {
      constructor(type) { this.type = type; }
    },
  };
  vm.runInNewContext(source, context);
  const result = await context.MaliangWebAIAdapter.submitPrompt(
    { sendSelectors: ["button"] },
    { focus() {}, dispatchEvent(event) { events.push(event.type); } },
    1,
  );
  assert.equal(result, "enter");
  assert.deepEqual(events, ["keydown", "keypress", "keyup"]);
});

test("extension executes only packaged scripts", () => {
  const policy = manifest.content_security_policy.extension_pages;
  assert.match(policy, /script-src 'self'/);
  assert.equal(policy.includes("unsafe-eval"), false);
});

test("chapter bodies use session storage, not local storage", async () => {
  const background = await readFile(new URL("background.js", root), "utf8");
  assert.match(background, /storage\.session\.set\(\{ activeMaliangJob/);
  assert.doesNotMatch(background, /storage\.local\.set\(\{ activeMaliangJob/);
});

test("an expired active-job lease cannot block polling forever", async () => {
  const background = await readFile(new URL("background.js", root), "utf8");
  assert.match(background, /function leaseIsExpired/);
  assert.match(background, /Date\.parse\(job\?\.leased_until/);
  assert.match(background, /storage\.session\.remove\(\["activeMaliangJob", "activeMaliangTabId"\]\)/);
  assert.match(background, /const activeJob = await recoverActiveJob\(\)/);
});

test("successful job events refresh the local lease and can rehydrate a lost active job", async () => {
  const background = await readFile(new URL("background.js", root), "utf8");
  const executor = await readFile(new URL("content/web-ai-executor.js", root), "utf8");
  assert.match(background, /async function refreshActiveJob\(jobSnapshot, serverJob = \{\}\)/);
  assert.match(background, /leased_until: serverJob\.leased_until/);
  assert.match(background, /await refreshActiveJob\(job, serverJob \|\| \{\}\)/);
  assert.match(background, /!active && snapshot\?\.id === message\.jobId/);
  assert.match(executor, /jobSnapshot: browserAIJob/);
  assert.match(executor, /eventType: "LEASE_RENEWED"/);
  assert.match(background, /includes\(serverAcceptedStatus\)/);
});

test("DeepSeek generation uses activity evidence and only starts idle failure from an explicit send state", async () => {
  const adapter = await readFile(new URL("content/web-ai-adapter.js", root), "utf8");
  const contract = await readFile(new URL("content/web-ai-contract.js", root), "utf8");
  assert.match(adapter, /function generationEvidence\(definition, input, progressChanged = false\)/);
  assert.match(adapter, /answerChanged \|\| reasoningChanged/);
  assert.match(adapter, /now - lastActivityAt < 2_500/);
  assert.match(adapter, /const idleControl = firstVisible\(definition\.idleSelectors/);
  assert.match(adapter, /health\.state === "healthy" && idle && !valid/);
  assert.match(contract, /generatingTexts/);
  assert.match(contract, /idleSelectors/);
  assert.match(contract, /stop-button/);
  assert.match(contract, /answerContainerSelectors/);
  assert.match(adapter, /completeStructuredEnvelope/);
});

test("structured extraction repairs DeepSeek raw newlines and trailing commas", async () => {
  const source = await readFile(new URL("content/web-ai-adapter.js", root), "utf8");
  const context = {
    MaliangWebAIContract: { providers: {} }, location: { hostname: "chat.deepseek.com" },
    document: { querySelectorAll: () => [] }, getComputedStyle: () => ({ visibility: "visible", display: "block" }),
    setTimeout,
  };
  vm.runInNewContext(source, context);
  const raw = '<MODEL_JSON>{"title":"first\nsecond","items":[1,2,],}</MODEL_JSON>';
  const parsed = context.MaliangWebAIAdapter.extractStructured(raw);
  assert.equal(parsed.title, "first\nsecond");
  assert.deepEqual([...parsed.items], [1, 2]);
});

test("a complete malformed JSON envelope is preserved and not auto-retried", async () => {
  const adapter = await readFile(new URL("content/web-ai-adapter.js", root), "utf8");
  assert.match(adapter, /INVALID_MODEL_JSON_COMPLETE/);
  assert.match(adapter, /the conversation was preserved/);
  assert.match(adapter, /false,\s*\n\s*\);/);
});

test("dispatch actively signals an existing target page so the next job starts", async () => {
  const background = await readFile(new URL("background.js", root), "utf8");
  assert.match(background, /if \(tab\.url !== url\) await chrome\.tabs\.update/);
  assert.match(background, /chrome\.tabs\.sendMessage\(tabId, \{ type: "RUN_ACTIVE_JOB" \}\)/);
  assert.match(background, /await signalContentScript\(tabId\)/);
  assert.match(background, /if \(phase === 0\) await chrome\.tabs\.reload\(tabId\)/);

  const executor = await readFile(new URL("content/executor.js", root), "utf8");
  assert.match(executor, /message\?\.type !== "RUN_ACTIVE_JOB"/);
  assert.match(executor, /sendResponse\(\{ accepted: true \}\)/);
});

test("Playwright contract is packaged before the adapter and task runner", async () => {
  const scripts = manifest.content_scripts[0].js;
  assert.deepEqual(scripts, [
    "lib/adapter-contract.js",
    "content/dom-driver.js",
    "content/fanqie-adapter.js",
    "content/executor.js",
  ]);
  const generated = await readFile(new URL("lib/adapter-contract.js", root), "utf8");
  assert.match(generated, /Generated from fanqie-core\/fanqie_core\/adapter_contract\.json/);
  assert.match(generated, /"source": "playwright_fanqie_client"/);
});

test("Fanqie React and ProseMirror fields receive browser editing events", async () => {
  const driver = await readFile(new URL("content/dom-driver.js", root), "utf8");
  assert.match(driver, /execCommand\("insertText"/);
  assert.match(driver, /execCommand\("selectAll"/);
});

test("book discovery ports Playwright DOM rules and avoids removed list APIs", async () => {
  const background = await readFile(new URL("background.js", root), "utf8");
  assert.match(background, /FANQIE_BOOK_MANAGE = `\$\{FANQIE_WRITER\}\/book-manage`/);
  assert.match(background, /\["CHECK_SESSION", "LIST_BOOKS", "CREATE_BOOK"\]\.includes\(job\.operation\)/);

  const adapter = await readFile(new URL("content/fanqie-adapter.js", root), "utf8");
  const driver = await readFile(new URL("content/dom-driver.js", root), "utf8");
  assert.match(adapter, /contract\.selectors\.book_links/);
  assert.match(adapter, /暂无作品\|还没有作品\|暂无小说/);
  assert.doesNotMatch(adapter, /我的小说\|暂无作品\|创建新书/);
  assert.match(adapter, /contract\.selectors\.book_nodes/);
  assert.match(adapter, /contract\.actions\.create_book/);
  assert.match(adapter, /preparedEntry = dom\.action\(\["创建书本"\]\)/);
  assert.match(driver, /\.write-button,/);
  assert.match(driver, /const hover = \(element\)/);
  assert.match(adapter, /entry\.matches\("\.write-button"\)/);
  assert.match(adapter, /dom\.action\(\["选择封面"\]\)/);
  assert.match(adapter, /\.cover-modal/);
  assert.match(adapter, /essay-activity-item-radio-icon-selected/);
  assert.doesNotMatch(adapter, /\/api\/author\/book\/list\/v[01]/);
  assert.match(adapter, /error|coded/);
});

test("chapter discovery follows verified icon pagers and reports completeness honestly", async () => {
  const adapter = await readFile(new URL("content/fanqie-adapter.js", root), "utf8");
  assert.match(adapter, /function nextPageControl/);
  assert.match(adapter, /aria-label/);
  assert.match(adapter, />›»/);
  assert.match(adapter, /chapters_complete: listed\.complete/);
  assert.doesNotMatch(adapter, /chapters_complete: true/);
});

test("popup settings restore the persisted device connection", async () => {
  const api = await readFile(new URL("lib/api.js", root), "utf8");
  assert.match(api, /"connected"/);
  assert.match(api, /"deviceRecordId"/);
  assert.match(api, /"workspaceId"/);
});

test("manifest icons are packaged raster assets", async () => {
  for (const path of Object.values(manifest.icons)) {
    assert.match(path, /\.png$/);
    assert.ok((await stat(new URL(path, root))).size > 100);
  }
});

test("long-running page work renews its lease every 30 seconds", async () => {
  const executor = await readFile(new URL("content/executor.js", root), "utf8");
  assert.match(executor, /LEASE_RENEWED/);
  assert.match(executor, /30000/);
  assert.match(executor, /AMBIGUOUS_RESULT/);
  assert.match(executor, /ambiguous_reconciled_absent/);
});

test("platform daily limits are deferred instead of blindly retried", async () => {
  const executor = await readFile(new URL("content/executor.js", root), "utf8");
  const background = await readFile(new URL("background.js", root), "utf8");
  assert.match(executor, /RATE_LIMITED/);
  assert.match(executor, /nextShanghaiRetryAfter/);
  assert.match(executor, /更新作品数/);
  assert.match(background, /deferActive/);
  assert.match(background, /JOB_DEFER/);
});

test("adapter ports Playwright publish safety flow", async () => {
  const adapter = await readFile(new URL("content/fanqie-adapter.js", root), "utf8");
  const network = await readFile(new URL("content/net-hook.js", root), "utf8");
  assert.match(adapter, /错别字未修改/);
  assert.match(adapter, /请选择内容检测方式/);
  assert.match(adapter, /内容风险检测/);
  assert.match(adapter, /selectAiYes/);
  assert.match(adapter, /role="radiogroup"/);
  assert.match(adapter, /waitPublishSettings/);
  assert.match(adapter, /settlePublishDialogs/);
  assert.match(adapter, /innerText \|\| ""\)\.trim\(\) === "确认发布"/);
  assert.match(adapter, /configureSchedule/);
  assert.match(adapter, /role="switch"/);
  assert.match(adapter, /定时发布时间回读不一致/);
  assert.match(adapter, /reconcileAmbiguous/);
  assert.match(adapter, /createNetworkResult/);
  assert.match(adapter, /番茄章节标题需为 5 至 30 个字/);
  assert.match(adapter, /番茄编辑器未确认标题或正文字数/);
  assert.doesNotMatch(adapter, /arco-message-success/);
  assert.match(network, /book\\\/create/);
  assert.match(network, /platform_book_id/);
});

test("Fanqie login forms override generic writer-page text", async () => {
  const adapter = await readFile(new URL("content/fanqie-adapter.js", root), "utf8");
  const contract = await readFile(new URL("lib/adapter-contract.js", root), "utf8");
  const background = await readFile(new URL("background.js", root), "utf8");
  assert.match(adapter, /\\\/login/);
  assert.match(adapter, /managementPage/);
  assert.match(adapter, /authorVisible/);
  assert.match(adapter, /settledIdentity/);
  assert.match(adapter, /payload\.expected_author_name \|\| payload\.expected_author_id/);
  assert.match(adapter, /job\.operation !== "CHECK_SESSION"/);
  assert.match(contract, /验证码登录/);
  assert.match(contract, /登录\/注册/);
  assert.match(background, /\["CHECK_SESSION", "LIST_BOOKS", "CREATE_BOOK"\]/);
});
