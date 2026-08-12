import path from "node:path";
import { BrowserProviderAdapter } from "./providers/browser-adapter.js";
import { loadProviderDefinitions } from "./providers/definitions.js";

const providerId = process.argv[2] ?? "";
const definitions = loadProviderDefinitions();
const definition = definitions[providerId];

if (!definition) {
  console.error(`未知渠道：${providerId || "(未提供)"}`);
  console.error(`可用渠道：${Object.keys(definitions).join(", ")}`);
  process.exit(1);
}

const adapter = new BrowserProviderAdapter(
  definition,
  path.resolve(process.env.WEB_AI_PROFILE_ROOT ?? ".profiles"),
  false,
);

try {
  await adapter.openForLogin();
  console.log(`请在浏览器中手动登录 ${definition.label}；确认成功后关闭整个浏览器窗口以保存状态...`);
  await adapter.waitForManualLoginClose(
    Number(process.env.WEB_AI_LOGIN_TIMEOUT_MS ?? 10 * 60_000),
  );
  console.log(`${definition.label} 登录状态已保存。`);
} finally {
  await adapter.close();
}
