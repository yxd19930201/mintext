(() => {
  "use strict";

  const adapter = globalThis.MaliangWebAIAdapter;
  const cleanup = globalThis.MaliangConversationCleanup;
  if (!adapter) throw new Error("Maliang web AI adapter was not loaded");
  if (!cleanup) throw new Error("Maliang conversation cleanup was not loaded");

  async function reportProviderState() {
    const state = await adapter.probe();
    if (state.provider) {
      await chrome.runtime.sendMessage({ type: "WEB_AI_PROVIDER_STATE", provider: state.provider, state });
    }
  }

  async function reportCleanupState(provider, state) {
    return chrome.runtime.sendMessage({
      type: "WEB_AI_SESSION_CLEANUP_STATE",
      provider,
      state: { ...state, last_run_at: new Date().toISOString() },
    });
  }

  async function removeCommittedSession(job, result) {
    const definition = adapter.definitionForPage();
    if (!definition || definition.id !== job.payload?.provider) return null;
    const context = await chrome.runtime.sendMessage({ type: "WEB_AI_PAGE_CONTEXT", provider: definition.id });
    if (!context?.data?.managed) {
      await reportCleanupState(definition.id, {
        status: "preserved", deleted: false, reason: "not_extension_managed_tab",
      });
      return null;
    }
    return cleanup.remove(definition, result.conversation_url, {
      report: (state) => reportCleanupState(definition.id, state),
    });
  }

  async function completeFailedJob(job, error) {
    if (error.code === "NAVIGATION_PENDING") return { navigating: true };
    const waiting = ["AUTH_REQUIRED", "HUMAN_VERIFICATION_REQUIRED"].includes(error.code);
    const status = error.code === "CANCELLED" ? "cancelled"
      : waiting ? "waiting_user" : error.code === "ADAPTER_OUTDATED" ? "adapter_outdated" : "failed";
    return chrome.runtime.sendMessage({
      type: "JOB_COMPLETE",
      jobSnapshot: job,
      status,
      result: {
        provider: job.payload?.provider,
        url: location.href,
        code: error.code || "WEB_AI_ERROR",
        retryable: Boolean(error.retryable),
        execution_phase: error.executionPhase || "failed",
        page_health: error.pageHealth || "unknown",
        conversation_preserved: true,
      },
      error: error.message,
    });
  }

  async function start() {
    await reportProviderState().catch(() => {});
    const response = await chrome.runtime.sendMessage({ type: "CONTENT_READY" });
    const job = response?.data?.job;
    const browserAIJob = job?.kind === "browser_ai" ? job : null;
    if (!browserAIJob) return;

    await chrome.runtime.sendMessage({
      type: "JOB_EVENT",
      jobId: browserAIJob.id,
      jobSnapshot: browserAIJob,
      eventType: "STARTED",
      payload: { url: location.href, provider: browserAIJob.payload?.provider },
    });
    const leaseRenewal = window.setInterval(() => {
      chrome.runtime.sendMessage({
        type: "JOB_EVENT", jobId: browserAIJob.id, eventType: "LEASE_RENEWED",
        jobSnapshot: browserAIJob,
        payload: { url: location.href, provider: browserAIJob.payload?.provider },
      }).catch(() => {});
    }, 30_000);

    try {
      let result;
      try {
        result = await adapter.execute(browserAIJob, {
          onProgress: async (progress) => {
            const response = await chrome.runtime.sendMessage({
              type: "JOB_EVENT", jobId: browserAIJob.id, eventType: "STREAM_PROGRESS", payload: progress,
              jobSnapshot: browserAIJob,
            });
            return response?.data || null;
          },
        });
      } catch (error) {
        const failed = await completeFailedJob(browserAIJob, error);
        if (failed?.navigating) return;
        await reportProviderState().catch(() => {});
        return;
      }

      // Only remove the exact session after the SaaS backend has acknowledged
      // the completed result. A failed acknowledgement always preserves it.
      const committed = await chrome.runtime.sendMessage({
        type: "JOB_COMPLETE",
        jobSnapshot: browserAIJob,
        status: "completed",
        result,
        holdClaimForCleanup: true,
      });
      if (!committed?.ok || !committed.data?.committed) {
        await adapter.rejectLedgerAnswer(
          browserAIJob.payload?.provider,
          result.output_text,
        ).catch(() => {});
        throw new Error(committed?.error || "任务结果尚未被系统确认，本次网页会话已保留");
      }

      try {
        await removeCommittedSession(browserAIJob, result);
        await adapter.clearLedger(browserAIJob.payload?.provider);
      } catch (error) {
        console.warn("[maliang-session-cleanup]", error);
      } finally {
        await chrome.runtime.sendMessage({
          type: "WEB_AI_SESSION_CLEANUP_FINISHED",
          provider: browserAIJob.payload?.provider,
          jobId: browserAIJob.id,
        }).catch(() => {});
      }
      await reportProviderState().catch(() => {});
    } finally {
      window.clearInterval(leaseRenewal);
    }
  }

  let running = false;
  function runActiveJob() {
    if (running) return;
    running = true;
    start().catch((error) => console.error("[maliang-web-ai]", error)).finally(() => { running = false; });
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "PROBE_WEB_AI") {
      adapter.probe().then((state) => sendResponse({ ok: true, state })).catch((error) => {
        sendResponse({ ok: false, error: error.message });
      });
      return true;
    }
    if (message?.type !== "RUN_ACTIVE_JOB") return false;
    runActiveJob();
    sendResponse({ accepted: true });
    return false;
  });

  runActiveJob();
})();
