const DEFAULT_API_BASE = "http://127.0.0.1:8000/api/v1";

function trimBase(value) {
  return String(value || DEFAULT_API_BASE).replace(/\/$/, "");
}

async function settings() {
  const value = await chrome.storage.local.get([
    "apiBase", "accessToken", "refreshToken", "deviceId", "deviceRecordId",
    "workspaceId", "connected", "lastError", "lastErrorAt",
    "webAiProviderStates", "webAiSessionCleanupStates",
  ]);
  return { ...value, apiBase: trimBase(value.apiBase) };
}

async function storeTokens(data) {
  await chrome.storage.local.set({
    accessToken: data.access_token,
    refreshToken: data.refresh_token,
    deviceRecordId: data.device_id,
    workspaceId: data.workspace_id,
    connected: true,
  });
}

export async function api(path, options = {}) {
  const value = await settings();
  const response = await fetch(`${value.apiBase}${path}`, {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(value.accessToken ? { Authorization: `Bearer ${value.accessToken}` } : {}),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || (payload?.code && payload.code !== "OK")) {
    throw new Error(payload?.message || `青玉本地接口失败（${response.status}）`);
  }
  return payload?.data;
}

export async function ensureDeviceId() {
  const stored = await chrome.storage.local.get("deviceId");
  if (stored.deviceId) return stored.deviceId;
  const deviceId = `browser-${crypto.randomUUID()}`;
  await chrome.storage.local.set({ deviceId });
  return deviceId;
}

export async function connectMaliang() {
  const value = await settings();
  const deviceId = await ensureDeviceId();
  const response = await fetch(`${value.apiBase}/browser-extension/connect`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      device_id: deviceId,
      browser: navigator.userAgent.includes("Edg/") ? "edge" : "chrome",
      extension_version: chrome.runtime.getManifest().version,
      display_name: "青玉浏览器助手",
    }),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.data) {
    throw new Error(payload?.message || "无法连接本机青玉书房服务");
  }
  await storeTokens(payload.data);
  return payload.data;
}

export async function disconnect() {
  await api("/browser-extension/disconnect", { method: "POST" }).catch(() => null);
  await chrome.storage.local.remove([
    "accessToken", "refreshToken", "deviceRecordId", "workspaceId", "connected",
  ]);
}

export async function configureApiBase(apiBase) {
  await chrome.storage.local.set({ apiBase: trimBase(apiBase) });
}

export { settings };
