import fs from "node:fs/promises";
import path from "node:path";

/** Playwright / system browser channel used by AI web + Fanqie. */
export type BrowserChannel = "chrome" | "msedge" | "bundled" | "auto";

/** Auto install order: Edge first (preinstalled on Windows), then Chrome. */
export const AUTO_SYSTEM_CHANNEL_ORDER: Array<"msedge" | "chrome"> = ["msedge", "chrome"];

export function normalizeBrowserChannel(raw: string | undefined | null): BrowserChannel {
  const value = (raw ?? "").trim().toLowerCase();
  if (value === "chrome" || value === "msedge" || value === "auto") return value;
  if (value === "bundled" || value === "chromium" || value === "none" || value === "playwright") {
    return "bundled";
  }
  return "auto";
}

/**
 * If PROFILE_ROOT ends with chrome|msedge, prefer that channel so the
 * executable always matches the user-data-dir brand.
 */
export function channelFromProfileRoot(profileRoot?: string | null): "chrome" | "msedge" | null {
  if (!profileRoot) return null;
  const base = path.basename(path.resolve(profileRoot)).toLowerCase();
  if (base === "chrome" || base === "msedge") return base;
  return null;
}

/**
 * Resolve channel from env (provider-specific → global → profile root → auto).
 * Mirrors fanqie-core / start.ps1: use whatever system browser is installed.
 */
export function readConfiguredBrowserChannel(providerId?: string): BrowserChannel {
  if (providerId) {
    const providerKey = `WEB_AI_${providerId.toUpperCase()}_BROWSER_CHANNEL`;
    const providerValue = process.env[providerKey];
    if (providerValue != null && providerValue.trim() !== "") {
      return normalizeBrowserChannel(providerValue);
    }
  }
  const globalValue = process.env.WEB_AI_BROWSER_CHANNEL;
  if (globalValue != null && globalValue.trim() !== "") {
    return normalizeBrowserChannel(globalValue);
  }
  // Missing env (broken launcher): still align with profile root when present.
  const fromProfile = channelFromProfileRoot(process.env.WEB_AI_PROFILE_ROOT);
  if (fromProfile) return fromProfile;
  return "auto";
}

function chromeCandidates(env: NodeJS.ProcessEnv = process.env): string[] {
  return [
    path.join(env.PROGRAMFILES ?? "", "Google/Chrome/Application/chrome.exe"),
    path.join(env["PROGRAMFILES(X86)"] ?? "", "Google/Chrome/Application/chrome.exe"),
    path.join(env.LOCALAPPDATA ?? "", "Google/Chrome/Application/chrome.exe"),
  ].filter(Boolean);
}

function edgeCandidates(env: NodeJS.ProcessEnv = process.env): string[] {
  return [
    path.join(env["PROGRAMFILES(X86)"] ?? "", "Microsoft/Edge/Application/msedge.exe"),
    path.join(env.PROGRAMFILES ?? "", "Microsoft/Edge/Application/msedge.exe"),
  ].filter(Boolean);
}

export function systemBrowserCandidates(
  channel: "chrome" | "msedge",
  env: NodeJS.ProcessEnv = process.env,
): string[] {
  return channel === "msedge" ? edgeCandidates(env) : chromeCandidates(env);
}

export async function pathExists(candidate: string): Promise<boolean> {
  try {
    await fs.access(candidate);
    return true;
  } catch {
    return false;
  }
}

/** Detect installed system browser. Priority: Edge > Chrome. */
export async function detectInstalledSystemChannel(
  env: NodeJS.ProcessEnv = process.env,
): Promise<"chrome" | "msedge" | null> {
  for (const name of AUTO_SYSTEM_CHANNEL_ORDER) {
    for (const candidate of systemBrowserCandidates(name, env)) {
      if (await pathExists(candidate)) return name;
    }
  }
  return null;
}

/**
 * Concrete channel for launch: never returns "auto".
 * auto → Edge if installed → Chrome if installed → bundled.
 */
export async function resolveBrowserChannel(
  configured: BrowserChannel = readConfiguredBrowserChannel(),
  env: NodeJS.ProcessEnv = process.env,
): Promise<"chrome" | "msedge" | "bundled"> {
  if (configured === "chrome" || configured === "msedge" || configured === "bundled") {
    // Explicit channel: if that browser is missing, fall back rather than crash.
    if (configured === "bundled") return "bundled";
    for (const candidate of systemBrowserCandidates(configured, env)) {
      if (await pathExists(candidate)) return configured;
    }
    const detected = await detectInstalledSystemChannel(env);
    return detected ?? "bundled";
  }
  const detected = await detectInstalledSystemChannel(env);
  return detected ?? "bundled";
}

/** Try channels in priority order for flexible launch. */
export function channelTryOrder(
  preferred: "chrome" | "msedge" | "bundled" | "auto",
): Array<"msedge" | "chrome"> {
  if (preferred === "msedge") return ["msedge", "chrome"];
  if (preferred === "chrome") return ["chrome", "msedge"];
  if (preferred === "bundled") return [];
  return [...AUTO_SYSTEM_CHANNEL_ORDER];
}

/** Executable path for CDP system-browser launch. */
export async function resolveSystemBrowserExecutable(
  channel: "chrome" | "msedge" | "auto" | "bundled",
  env: NodeJS.ProcessEnv = process.env,
): Promise<{ channel: "chrome" | "msedge"; executable: string }> {
  const order = channelTryOrder(channel);

  if (order.length === 0) {
    throw new Error("bundled 渠道没有系统可执行文件路径");
  }

  for (const name of order) {
    for (const candidate of systemBrowserCandidates(name, env)) {
      if (await pathExists(candidate)) {
        return { channel: name, executable: candidate };
      }
    }
  }

  throw new Error("未找到系统浏览器 Edge 或 Chrome");
}

/** Playwright launch options fragment: omit channel for bundled. */
export function playwrightChannelOption(
  channel: "chrome" | "msedge" | "bundled",
): { channel?: "chrome" | "msedge" } {
  return channel === "bundled" ? {} : { channel };
}

/**
 * Profile directory for a channel. Keeps Edge and Chrome user-data separate
 * so we never open Chrome with an Edge profile (immediate process exit).
 */
export function profilePathForChannel(
  profileRoot: string,
  providerId: string,
  channel: "chrome" | "msedge" | "bundled",
): string {
  const rootBase = path.basename(path.resolve(profileRoot)).toLowerCase();
  if (channel === "bundled" || rootBase === channel) {
    return path.resolve(profileRoot, providerId);
  }
  // profileRoot is .../.profiles-system/msedge but we fell back to chrome (or reverse)
  const parent = path.dirname(path.resolve(profileRoot));
  return path.resolve(parent, channel, providerId);
}
