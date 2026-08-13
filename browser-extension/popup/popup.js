import { configureApiBase, settings } from "../lib/api.js";

const $ = (id) => document.getElementById(id);

function message(value, error = false) {
  $("message").textContent = value || "";
  $("message").classList.toggle("error", error);
}

function providerLabel(state) {
  if (state?.ready) return "已登录，可执行";
  if (state?.state === "verification_required") return "需要人工验证";
  if (state?.state === "login_required") return "需要登录";
  return "打开网页后检测";
}

function cleanupLabel(state) {
  if (!state) return "任务会话：完成后单条删除";
  if (state.status === "deleting") return "任务会话：正在删除本次会话";
  if (state.status === "deleted") return "任务会话：本次会话已删除";
  if (state.status === "preserved") return `任务会话：已保留（${state.error || "无法唯一确认"}）`;
  return "任务会话：完成后单条删除";
}

async function send(type, extra = {}) {
  const response = await chrome.runtime.sendMessage({ type, ...extra });
  if (!response?.ok) throw new Error(response?.error || "扩展后台没有响应");
  return response.data;
}

async function render() {
  const value = await settings();
  $("api-base").value = value.apiBase;
  $("connect-panel").hidden = Boolean(value.connected);
  $("connected-panel").hidden = !value.connected;
  $("web-ai-panel").hidden = !value.connected;
  $("status").textContent = value.connected ? "已连接" : "未连接";
  $("status").className = `status ${value.connected ? "online" : "offline"}`;
  $("workspace").textContent = value.workspaceId || "—";
  $("device").textContent = value.deviceRecordId || value.deviceId || "—";
  $("last-error").textContent = value.lastError || "无";
  const providerStates = value.webAiProviderStates || {};
  const cleanupStates = value.webAiSessionCleanupStates || {};
  $("chatgpt-state").textContent = providerLabel(providerStates.chatgpt);
  $("deepseek-state").textContent = providerLabel(providerStates.deepseek);
  $("chatgpt-cleanup").textContent = cleanupLabel(cleanupStates.chatgpt);
  $("deepseek-cleanup").textContent = cleanupLabel(cleanupStates.deepseek);
}

async function busy(button, task) {
  button.disabled = true;
  message("处理中…");
  try {
    await task();
    message("操作完成");
    await render();
  } catch (error) {
    message(error.message, true);
  } finally {
    button.disabled = false;
  }
}

$("save-api").addEventListener("click", () => busy($("save-api"), async () => {
  await configureApiBase($("api-base").value);
}));
$("connect").addEventListener("click", () => busy($("connect"), () => send("CONNECT_MALIANG")));
$("claim").addEventListener("click", () => busy($("claim"), () => send("CLAIM_NOW")));
$("disconnect").addEventListener("click", () => busy($("disconnect"), () => send("DISCONNECT_MALIANG")));
$("open-chatgpt").addEventListener("click", () => busy($("open-chatgpt"), () => send("OPEN_WEB_AI", { provider: "chatgpt" })));
$("open-deepseek").addEventListener("click", () => busy($("open-deepseek"), () => send("OPEN_WEB_AI", { provider: "deepseek" })));

render();
