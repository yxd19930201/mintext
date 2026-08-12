import fs from "node:fs";
import path from "node:path";
import type { ProviderId } from "../contracts.js";

export interface ProviderDefinition {
  id: ProviderId;
  label: string;
  homeUrl: string;
  conversationUrlPattern?: string;
  inputSelectors: string[];
  sendSelectors: string[];
  assistantSelectors: string[];
  newConversationSelectors: string[];
  stopSelectors: string[];
  loginIndicators: string[];
  deleteMenuSelectors: string[];
  deleteActionSelectors: string[];
  deleteConfirmSelectors: string[];
  fastModeSelectors: string[];
  qualityModeSelectors: string[];
  modeMenuSelectors: string[];
  disableFeatureSelectors: string[];
  modelMenuSelectors: string[];
  modelOptionSelectors: string[];
  currentModelSelectors: string[];
}

const common = {
  sendSelectors: [
    'button[aria-label*="发送"]',
    'button[aria-label*="Send"]',
    'button[type="submit"]',
  ],
  stopSelectors: [
    'button[aria-label*="停止"]',
    'button[aria-label*="Stop"]',
    'button:has-text("停止生成")',
  ],
  loginIndicators: [
    'button:has-text("登录")',
    'button:has-text("Log in")',
    'a:has-text("登录")',
    'a:has-text("Sign in")',
  ],
  deleteMenuSelectors: [
    'button[aria-label*="更多"]',
    'button[aria-label*="More"]',
  ],
  deleteActionSelectors: [
    'text="删除对话"',
    'text="删除会话"',
    'text="Delete conversation"',
    'text="Delete chat"',
  ],
  deleteConfirmSelectors: [
    'button:has-text("确认删除")',
    'button:has-text("删除")',
    'button:has-text("Delete")',
  ],
  fastModeSelectors: [],
  qualityModeSelectors: [],
  modeMenuSelectors: [],
  disableFeatureSelectors: [],
  modelMenuSelectors: [],
  modelOptionSelectors: [],
  currentModelSelectors: [],
};

export const builtInProviders: Record<string, ProviderDefinition> = {
  deepseek: {
    ...common,
    id: "deepseek",
    label: "DeepSeek",
    homeUrl: "https://chat.deepseek.com/",
    conversationUrlPattern: "/a/chat/s/",
    inputSelectors: [
      'textarea[placeholder*="DeepSeek"]',
      'textarea[placeholder*="发送消息"]',
      "textarea",
    ],
    assistantSelectors: [
      '[data-role="assistant"]',
      '[class*="assistant"] [class*="markdown"]',
      ".ds-markdown",
      '[class*="markdown"]',
    ],
    newConversationSelectors: [
      'button:has-text("开启新对话")',
      'button:has-text("新对话")',
      'a:has-text("开启新对话")',
    ],
    loginIndicators: [
      'button:has-text("登录")',
      'input[type="password"]',
      'input[placeholder*="手机号"]',
      'input[placeholder*="邮箱"]',
      ...common.loginIndicators,
    ],
    fastModeSelectors: [
      '[role="radio"]:has-text("快速模式")',
      'label:has-text("快速模式")',
      'text="快速模式"',
    ],
    qualityModeSelectors: [
      '[role="radio"]:has-text("专家模式")',
      'label:has-text("专家模式")',
      'text="专家模式"',
    ],
    // DeepSeek only keeps the selected mode visible. The selected-mode control
    // opens the popover containing the other mode, so it must also be used for
    // capability discovery and for switching from fast to expert mode.
    modeMenuSelectors: [
      'button:has-text("快速模式")',
      'button:has-text("专家模式")',
      '[role="button"]:has-text("快速模式")',
      '[role="button"]:has-text("专家模式")',
    ],
    disableFeatureSelectors: ['text="智能搜索"'],
    currentModelSelectors: [
      '[role="radio"][aria-checked="true"]',
      '[class*="model"] [aria-checked="true"]',
    ],
  },
  chatgpt: {
    ...common,
    id: "chatgpt",
    label: "ChatGPT",
    homeUrl: "https://chatgpt.com/",
    conversationUrlPattern: "/c/",
    inputSelectors: [
      '#prompt-textarea',
      'div[contenteditable="true"][data-virtualkeyboard="true"]',
      'textarea[placeholder*="Message"]',
      "textarea",
    ],
    sendSelectors: [
      'button[data-testid="send-button"]',
      'button[aria-label*="Send prompt"]',
      'button[aria-label*="发送提示"]',
      ...common.sendSelectors,
    ],
    stopSelectors: [
      'button[data-testid="stop-button"]',
      'button[aria-label*="Stop streaming"]',
      ...common.stopSelectors,
    ],
    assistantSelectors: [
      '[data-message-author-role="assistant"] .markdown',
      '[data-turn="assistant"] .markdown',
      'article[data-testid^="conversation-turn-"]:has([data-message-author-role="assistant"]) .markdown',
      '[data-message-author-role="assistant"]',
    ],
    newConversationSelectors: [
      'a[data-testid="create-new-chat-button"]',
      'a[aria-label*="New chat"]',
      'a[aria-label*="新聊天"]',
      'a[href="/"]',
    ],
    loginIndicators: [
      'button[data-testid="login-button"]',
      'button:has-text("Log in")',
      'button:has-text("登录")',
      'a:has-text("Log in")',
    ],
    deleteMenuSelectors: ['button[data-testid="conversation-options"]'],
    deleteActionSelectors: [
      '[role="menuitem"]:has-text("Delete")',
      '[role="menuitem"]:has-text("删除")',
    ],
    deleteConfirmSelectors: [
      'button[data-testid="delete-conversation-confirm-button"]',
      'button:has-text("Delete")',
      'button:has-text("删除")',
    ],
    modelMenuSelectors: [
      'button[data-testid="model-switcher-dropdown-button"]',
      'button[aria-label*="Model selector"]',
      'button:has-text("ChatGPT")',
    ],
    modelOptionSelectors: [
      '[role="menuitemradio"]',
      '[role="menuitem"]:has([data-testid*="model"])',
      '[data-testid*="model-switcher"] [role="option"]',
    ],
    currentModelSelectors: [
      'button[data-testid="model-switcher-dropdown-button"]',
      'button[aria-label*="Model selector"]',
    ],
  },
  doubao: {
    ...common,
    id: "doubao",
    label: "豆包",
    homeUrl: "https://www.doubao.com/chat/",
    conversationUrlPattern: "/chat/",
    inputSelectors: [
      'textarea[placeholder*="豆包"]',
      'textarea[placeholder*="发送"]',
      '[contenteditable="true"]',
      "textarea",
    ],
    assistantSelectors: [
      '[data-testid*="assistant"]',
      '[class*="assistant"] [class*="markdown"]',
      '[class*="message"] [class*="markdown"]',
    ],
    newConversationSelectors: [
      'button:has-text("新对话")',
      'button:has-text("新建对话")',
      'a:has-text("新对话")',
      'text="新对话"',
    ],
    modeMenuSelectors: [
      'button:has-text("快速")',
      'button:has-text("专家")',
    ],
    fastModeSelectors: ['[role="menuitem"]:has-text("快速")'],
    qualityModeSelectors: ['[role="menuitem"]:has-text("专家")'],
  },
  kimi: {
    ...common,
    id: "kimi",
    label: "Kimi",
    homeUrl: "https://www.kimi.com/",
    conversationUrlPattern: "/chat/",
    inputSelectors: [
      'textarea[placeholder*="Kimi"]',
      '[contenteditable="true"]',
      "textarea",
    ],
    assistantSelectors: [
      '[data-role="assistant"]',
      '[class*="assistant"] [class*="markdown"]',
      '[class*="segment-content"]',
    ],
    newConversationSelectors: [
      'button:has-text("新建会话")',
      'button:has-text("新对话")',
      'a:has-text("新建会话")',
    ],
  },
};

function mergeDefinition(
  base: ProviderDefinition | undefined,
  override: Partial<ProviderDefinition> & Pick<ProviderDefinition, "id">,
): ProviderDefinition {
  if (!base) {
    const required = ["label", "homeUrl", "inputSelectors", "assistantSelectors"] as const;
    for (const key of required) {
      if (!override[key]) throw new Error(`自定义渠道 ${override.id} 缺少 ${key}`);
    }
  }
  return { ...common, ...base, ...override } as ProviderDefinition;
}

export function loadProviderDefinitions(): Record<string, ProviderDefinition> {
  // Doubao/Kimi definitions remain in source for future work but are deliberately hidden.
  const definitions: Record<string, ProviderDefinition> = {
    deepseek: builtInProviders.deepseek!,
    chatgpt: builtInProviders.chatgpt!,
  };
  const customPath = process.env.WEB_AI_PROVIDER_CONFIG;
  if (!customPath) return definitions;

  const absolutePath = path.resolve(customPath);
  const overrides = JSON.parse(fs.readFileSync(absolutePath, "utf8")) as Array<
    Partial<ProviderDefinition> & Pick<ProviderDefinition, "id">
  >;
  for (const override of overrides) {
    if (!["deepseek", "chatgpt"].includes(override.id)) continue;
    definitions[override.id] = mergeDefinition(definitions[override.id], override);
  }
  return definitions;
}
