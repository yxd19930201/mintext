(() => {
  "use strict";

  const adapter = globalThis.MaliangFanqieAdapter;
  if (!adapter) throw new Error("Maliang Fanqie adapter was not loaded");

  function nextShanghaiRetryAfter() {
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
      timeZone: "Asia/Shanghai", year: "numeric", month: "numeric", day: "numeric",
    }).formatToParts(new Date()).filter((part) => part.type !== "literal")
      .map((part) => [part.type, Number(part.value)]));
    return new Date(Date.UTC(parts.year, parts.month - 1, parts.day + 1, 0, 10) - 8 * 3600000).toISOString();
  }

  async function start() {
    const response = await chrome.runtime.sendMessage({ type: "CONTENT_READY" });
    const job = response?.data?.job;
    if (!job) return;
    await chrome.runtime.sendMessage({
      type: "JOB_EVENT", jobId: job.id, eventType: "STARTED",
      payload: { url: location.href, adapter_contract_version: globalThis.MaliangFanqieContract.version },
    });
    const leaseRenewal = window.setInterval(() => {
      chrome.runtime.sendMessage({
        type: "JOB_EVENT", jobId: job.id, eventType: "LEASE_RENEWED", payload: { url: location.href },
      }).catch(() => {});
    }, 30000);
    try {
      const result = await adapter.execute(job);
      if (result?.identity_mismatch || result?.book_mismatch) {
        await chrome.runtime.sendMessage({
          type: "JOB_COMPLETE", status: "failed", result,
          error: "番茄账号或作品与青玉任务不匹配",
        });
      } else {
        const status = job.operation === "VERIFY_CHAPTER" && result.platform_verified ? "verified" : "processed";
        await chrome.runtime.sendMessage({ type: "JOB_COMPLETE", status, result });
      }
    } catch (error) {
      if (error.code === "AMBIGUOUS_RESULT") {
        try {
          const reconciled = await adapter.reconcileAmbiguous(job);
          if (reconciled) {
            await chrome.runtime.sendMessage({
              type: "JOB_COMPLETE",
              status: reconciled.platform_verified ? "verified" : "processed",
              result: reconciled,
            });
            return;
          }
          await chrome.runtime.sendMessage({
            type: "JOB_COMPLETE", status: "failed",
            result: { ambiguous_reconciled_absent: true },
            error: "回读确认平台不存在该目标，可以安全重试",
          });
          return;
        } catch (reconcileError) {
          await chrome.runtime.sendMessage({
            type: "JOB_COMPLETE", status: "waiting_user",
            result: { ambiguous_result: true },
            error: `提交结果不明确且回读失败：${reconcileError.message}`,
          });
          return;
        }
      }
      if (["CREATE_BOOK", "PUBLISH_CHAPTER", "OVERWRITE_CHAPTER"].includes(job.operation)
        && /每日上限|更新作品数|请求过于频繁|操作频繁|访问频繁|限流/.test(error.message || "")) {
        await chrome.runtime.sendMessage({
          type: "JOB_DEFER", eventType: "RATE_LIMITED",
          payload: {
            error: error.message,
            reason: "platform_daily_limit",
            retry_after: nextShanghaiRetryAfter(),
            url: location.href,
          },
        });
        return;
      }
      const status = error.code === "WAITING_USER" ? "waiting_user"
        : error.code === "ADAPTER_OUTDATED" ? "adapter_outdated" : "failed";
      await chrome.runtime.sendMessage({
        type: "JOB_COMPLETE", status,
        result: { url: location.href, ...(error.diagnostics ? { diagnostics: error.diagnostics } : {}) },
        error: error.message,
      });
    } finally {
      window.clearInterval(leaseRenewal);
    }
  }

  let running = false;
  function runActiveJob() {
    if (running) return;
    running = true;
    start().catch((error) => console.error("[maliang-extension]", error)).finally(() => { running = false; });
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== "RUN_ACTIVE_JOB") return false;
    runActiveJob();
    sendResponse({ accepted: true });
    return false;
  });

  runActiveJob();
})();
