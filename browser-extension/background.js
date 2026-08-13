import { api, connectMaliang, disconnect, settings } from "./lib/api.js";

const FANQIE_WRITER = "https://fanqienovel.com/main/writer";
const FANQIE_BOOK_MANAGE = `${FANQIE_WRITER}/book-manage`;
const WEB_AI_HOME = {
  chatgpt: "https://chatgpt.com/",
  deepseek: "https://chat.deepseek.com/",
};
let polling = false;

async function clearTransientError() {
  await chrome.storage.local.set({ lastError: null, lastErrorAt: null });
}

function leaseIsExpired(job) {
  const leasedUntil = Date.parse(job?.leased_until || "");
  return Number.isFinite(leasedUntil) && leasedUntil <= Date.now();
}

async function recoverActiveJob() {
  const state = await chrome.storage.session.get("activeMaliangJob");
  const job = state.activeMaliangJob;
  if (!job) return null;
  if (!leaseIsExpired(job)) return job;
  await chrome.storage.session.remove(["activeMaliangJob", "activeMaliangTabId"]);
  await chrome.storage.local.set({
    lastError: "Previous task lease expired; polling has resumed.",
    lastErrorAt: new Date().toISOString(),
  });
  return null;
}

async function refreshActiveJob(jobSnapshot, serverJob = {}) {
  if (!jobSnapshot?.id) return null;
  const state = await chrome.storage.session.get("activeMaliangJob");
  const active = state.activeMaliangJob;
  if (active && active.id !== jobSnapshot.id) return active;
  const refreshed = {
    ...(active || jobSnapshot),
    status: serverJob.status || active?.status || jobSnapshot.status,
    leased_until: serverJob.leased_until || active?.leased_until || jobSnapshot.leased_until,
    last_progress_at: serverJob.last_progress_at || active?.last_progress_at || jobSnapshot.last_progress_at,
  };
  await chrome.storage.session.set({ activeMaliangJob: refreshed });
  return refreshed;
}

async function sessionCleanupIsPending() {
  const stored = await chrome.storage.session.get("webAiSessionCleanupLock");
  const lock = stored.webAiSessionCleanupLock;
  if (!lock) return false;
  if (Number(lock.expiresAt || 0) > Date.now()) return true;
  await chrome.storage.session.remove("webAiSessionCleanupLock");
  return false;
}

async function heartbeat() {
  const value = await settings();
  if (!value.accessToken) return;
  const {
    webAiProviderStates = {}, webAiSessionCleanupStates = {},
  } = await chrome.storage.local.get(["webAiProviderStates", "webAiSessionCleanupStates"]);
  await api("/browser-extension/heartbeat", {
    method: "POST",
    body: JSON.stringify({
      browser: navigator.userAgent.includes("Edg/") ? "edge" : "chrome",
      extension_version: chrome.runtime.getManifest().version,
      metadata: {
        platform: navigator.platform,
        capabilities: ["fanqie_publish", "chatgpt_web", "deepseek_web"],
        web_ai: webAiProviderStates,
        session_cleanup: webAiSessionCleanupStates,
      },
    }),
  });
  await clearTransientError();
}

function targetUrl(job) {
  const payload = job.payload || {};
  if (job.kind === "browser_ai") return WEB_AI_HOME[payload.provider] || WEB_AI_HOME.chatgpt;
  if (["CHECK_SESSION", "LIST_BOOKS", "CREATE_BOOK"].includes(job.operation)) {
    return FANQIE_BOOK_MANAGE;
  }
  if (["PUBLISH_CHAPTER", "OVERWRITE_CHAPTER"].includes(job.operation)) {
    if (job.operation === "OVERWRITE_CHAPTER" && payload.platform_chapter_id) {
      return `${FANQIE_WRITER}/${payload.platform_book_id}/publish/${payload.platform_chapter_id}?enter_from=edit`;
    }
    return `${FANQIE_WRITER}/${payload.platform_book_id}/publish/?enter_from=newchapter`;
  }
  if (["LIST_CHAPTERS", "VERIFY_CHAPTER"].includes(job.operation)) {
    return `${FANQIE_WRITER}/chapter-manage/${payload.platform_book_id}?type=1`;
  }
  return FANQIE_WRITER;
}

async function findOrOpenFanqie(url) {
  const tabs = await chrome.tabs.query({ url: "https://fanqienovel.com/*" });
  const tab = tabs.find((value) => value.url?.includes("/main/writer"));
  if (tab) {
    if (tab.url !== url) await chrome.tabs.update(tab.id, { url, active: false });
    return tab.id;
  }
  const created = await chrome.tabs.create({ url, active: false });
  return created.id;
}

async function findOrOpenWebAI(provider, url) {
  const stored = await chrome.storage.local.get("managedAiTabs");
  const managed = { ...(stored.managedAiTabs || {}) };
  const existingId = managed[provider];
  if (existingId) {
    try {
      const tab = await chrome.tabs.get(existingId);
      if (tab?.id) {
        const job = (await chrome.storage.session.get("activeMaliangJob")).activeMaliangJob;
        const storedLedgers = await chrome.storage.local.get("webAiExecutionLedgers");
        const ledger = storedLedgers.webAiExecutionLedgers?.[provider];
        const sameExecution = Boolean(
          job?.payload?.idempotency_key
          && ledger?.idempotency_key === job.payload.idempotency_key
          && ledger?.provider === provider
        );
        if (!sameExecution && tab.url !== url) await chrome.tabs.update(tab.id, { url, active: false });
        return tab.id;
      }
    } catch (_) {
      delete managed[provider];
    }
  }
  const created = await chrome.tabs.create({ url, active: false });
  managed[provider] = created.id;
  await chrome.storage.local.set({ managedAiTabs: managed });
  return created.id;
}

async function findOrOpenTarget(job, url) {
  if (job.kind === "browser_ai") return findOrOpenWebAI(job.payload?.provider, url);
  return findOrOpenFanqie(url);
}

async function signalContentScript(tabId) {
  for (let phase = 0; phase < 2; phase += 1) {
    for (let attempt = 0; attempt < 60; attempt += 1) {
      try {
        const response = await chrome.tabs.sendMessage(tabId, { type: "RUN_ACTIVE_JOB" });
        if (response?.accepted) return;
      } catch (_) {
        // The tab may still be navigating and the content script is not ready yet.
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    // Reload once so an extension update injects the newest packaged content script.
    if (phase === 0) await chrome.tabs.reload(tabId);
  }
  throw new Error("目标网页已打开，但青玉内容脚本未就绪。");
}

async function dispatch(job) {
  await chrome.storage.session.set({ activeMaliangJob: job });
  const tabId = await findOrOpenTarget(job, targetUrl(job));
  await chrome.storage.session.set({ activeMaliangTabId: tabId });
  await signalContentScript(tabId);
}

async function claimLoop() {
  if (polling) return;
  polling = true;
  try {
    const value = await settings();
    if (!value.accessToken) return;
    if (await sessionCleanupIsPending()) return;
    const activeJob = await recoverActiveJob();
    if (activeJob) return;
    const data = await api("/browser-extension/jobs/claim?wait_seconds=25", { method: "POST" });
    await clearTransientError();
    const job = data?.job === null ? null : data;
    if (job?.id) await dispatch(job);
  } catch (error) {
    await chrome.storage.local.set({ lastError: error.message, lastErrorAt: new Date().toISOString() });
  } finally {
    polling = false;
  }
}

async function completeActive(status, result = {}, error = null, options = {}) {
  const state = await chrome.storage.session.get(["activeMaliangJob", "activeMaliangTabId"]);
  const active = state.activeMaliangJob;
  const snapshot = options.jobSnapshot;
  const job = active?.id === snapshot?.id || !snapshot ? active : (!active ? snapshot : null);
  if (!job) return;
  const completed = await api(`/browser-extension/jobs/${job.id}/complete`, {
    method: "POST",
    body: JSON.stringify({ status, result, error, lease_token: job.lease_token }),
  });
  const serverAcceptedStatus = completed?.status || status;
  const committed = status !== "completed" || serverAcceptedStatus === "completed";
  const holdForCleanup = Boolean(
    committed && options.holdForCleanup && status === "completed" && job.kind === "browser_ai"
  );
  if (holdForCleanup) {
    await chrome.storage.session.set({
      webAiSessionCleanupLock: {
        jobId: job.id,
        provider: job.payload?.provider,
        tabId: state.activeMaliangTabId || null,
        expiresAt: Date.now() + 60_000,
      },
    });
  }
  if (!active || active.id === job.id) {
    await chrome.storage.session.remove(["activeMaliangJob", "activeMaliangTabId"]);
  }
  if (["failed", "waiting_user", "adapter_outdated"].includes(serverAcceptedStatus)) {
    chrome.notifications.create({
      type: "basic", iconUrl: chrome.runtime.getURL("icons/icon128.png"),
      title: "青玉浏览器助手", message: error || "浏览器任务需要处理",
    }).catch(() => {});
  }
  if (holdForCleanup) setTimeout(claimLoop, 60_250);
  else setTimeout(claimLoop, 250);
  return { committed, status: serverAcceptedStatus, result: completed?.result || {}, cleanup_pending: holdForCleanup };
}

async function deferActive(eventType, payload = {}) {
  const { activeMaliangJob: job } = await chrome.storage.session.get("activeMaliangJob");
  if (!job) return;
  await api(`/browser-extension/jobs/${job.id}/events`, {
    method: "POST",
    body: JSON.stringify({ event_type: eventType, payload, lease_token: job.lease_token }),
  });
  await chrome.storage.session.remove(["activeMaliangJob", "activeMaliangTabId"]);
  chrome.notifications.create({
    type: "basic", iconUrl: chrome.runtime.getURL("icons/icon128.png"),
    title: "青玉浏览器助手", message: payload.error || "平台限额等待恢复",
  }).catch(() => {});
  setTimeout(claimLoop, 250);
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("maliang-heartbeat", { periodInMinutes: 1 });
  chrome.alarms.create("maliang-claim", { periodInMinutes: 1 });
});

chrome.runtime.onStartup.addListener(() => {
  heartbeat().catch(() => {});
  claimLoop();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "maliang-heartbeat") heartbeat().catch(() => {});
  if (alarm.name === "maliang-claim") claimLoop();
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    if (message.type === "CONNECT_MALIANG") return connectMaliang();
    if (message.type === "DISCONNECT_MALIANG") return disconnect();
    if (message.type === "CLAIM_NOW") return claimLoop();
    if (message.type === "OPEN_WEB_AI") {
      const url = WEB_AI_HOME[message.provider];
      if (!url) throw new Error("不支持的网页 AI 渠道");
      const tabId = await findOrOpenWebAI(message.provider, url);
      await chrome.tabs.update(tabId, { active: true });
      return { tabId };
    }
    if (message.type === "WEB_AI_PAGE_CONTEXT") {
      const stored = await chrome.storage.local.get("managedAiTabs");
      const managedTabId = stored.managedAiTabs?.[message.provider];
      return { managed: Boolean(sender.tab?.id && managedTabId === sender.tab.id), tabId: sender.tab?.id || null };
    }
    if (message.type === "WEB_AI_PROVIDER_STATE") {
      const stored = await chrome.storage.local.get("webAiProviderStates");
      const states = { ...(stored.webAiProviderStates || {}), [message.provider]: message.state };
      await chrome.storage.local.set({ webAiProviderStates: states });
      heartbeat().catch(() => {});
      return states[message.provider];
    }
    if (message.type === "WEB_AI_SESSION_CLEANUP_STATE") {
      const stored = await chrome.storage.local.get("webAiSessionCleanupStates");
      const states = { ...(stored.webAiSessionCleanupStates || {}), [message.provider]: message.state };
      await chrome.storage.local.set({ webAiSessionCleanupStates: states });
      return states[message.provider];
    }
    if (message.type === "WEB_AI_SESSION_CLEANUP_FINISHED") {
      const stored = await chrome.storage.session.get("webAiSessionCleanupLock");
      const lock = stored.webAiSessionCleanupLock;
      const sameTask = lock?.jobId === message.jobId && lock?.provider === message.provider;
      const sameTab = !lock?.tabId || lock.tabId === sender.tab?.id;
      if (sameTask && sameTab) {
        await chrome.storage.session.remove("webAiSessionCleanupLock");
        setTimeout(claimLoop, 250);
      }
      return { released: Boolean(sameTask && sameTab) };
    }
    if (message.type === "CONTENT_READY") {
      const state = await chrome.storage.session.get(["activeMaliangJob", "activeMaliangTabId"]);
      if (state.activeMaliangJob && (!state.activeMaliangTabId || state.activeMaliangTabId === sender.tab?.id)) {
        return { job: state.activeMaliangJob };
      }
      return { job: null };
    }
    if (message.type === "JOB_EVENT") {
      const { activeMaliangJob: active } = await chrome.storage.session.get("activeMaliangJob");
      const snapshot = message.jobSnapshot;
      const job = active?.id === message.jobId ? active : (!active && snapshot?.id === message.jobId ? snapshot : null);
      if (!job) return null;
      const serverJob = await api(`/browser-extension/jobs/${job.id}/events`, {
        method: "POST",
        body: JSON.stringify({ event_type: message.eventType, payload: message.payload || {}, lease_token: job.lease_token }),
      });
      await refreshActiveJob(job, serverJob || {});
      return serverJob;
    }
    if (message.type === "JOB_COMPLETE") {
      return completeActive(message.status, message.result, message.error, {
        holdForCleanup: message.holdClaimForCleanup,
        jobSnapshot: message.jobSnapshot,
      });
    }
    if (message.type === "JOB_DEFER") return deferActive(message.eventType, message.payload);
    return null;
  })().then((data) => sendResponse({ ok: true, data })).catch((error) => sendResponse({ ok: false, error: error.message }));
  return true;
});

heartbeat().catch(() => {});
claimLoop();
