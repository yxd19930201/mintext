import { JSON_CLOSE, JSON_OPEN } from "./json-envelope.js";
import type { GenerateRequest } from "../contracts.js";

export function buildPrompt(request: GenerateRequest): string {
  const schema = request.outputSchema ?? {
    type: "object",
    additionalProperties: true,
  };

  return [
    request.instruction ?? "根据输入完成任务。",
    `输入JSON:${JSON.stringify(request.input)}`,
    `输出Schema:${JSON.stringify(schema)}`,
    "若输出包含小说正文，content 字符串必须使用 \\n\\n 分隔自然段；禁止把整章正文压成单行。",
    `只输出${JSON_OPEN}合法JSON${JSON_CLOSE}；不要Markdown、解释、注释或尾随逗号。`,
  ].join("\n");
}
