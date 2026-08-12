import { Ajv, type ValidateFunction } from "ajv/dist/ajv.js";
import { jsonrepair } from "jsonrepair";
import { AdapterError } from "./errors.js";
import type { JsonSchema } from "../contracts.js";

export const JSON_OPEN = "<MODEL_JSON>";
export const JSON_CLOSE = "</MODEL_JSON>";

const ajv = new Ajv({ allErrors: true, strict: false });

function stripFence(value: string): string {
  return value
    .trim()
    .replace(/^```(?:json)?\s*/i, "")
    .replace(/\s*```$/i, "")
    .trim();
}

function extractMarked(text: string): string | null {
  const close = text.lastIndexOf(JSON_CLOSE);
  if (close < 0) return null;
  const open = text.lastIndexOf(JSON_OPEN, close);
  if (open < 0) return null;
  return text.slice(open + JSON_OPEN.length, close);
}

function extractFenced(text: string): string | null {
  const matches = [...text.matchAll(/```(?:json)?\s*([\s\S]*?)```/gi)];
  return matches.at(-1)?.[1] ?? null;
}

function extractBalancedObject(text: string): string | null {
  let depth = 0;
  let inString = false;
  let escaped = false;
  let end = -1;

  for (let index = text.length - 1; index >= 0; index -= 1) {
    if (!/\s/.test(text.charAt(index))) {
      end = index;
      break;
    }
  }
  if (end < 0 || !["}", "]"].includes(text.charAt(end))) return null;

  const closing = text[end];
  const opening = closing === "}" ? "{" : "[";
  for (let index = end; index >= 0; index -= 1) {
    const char = text[index];
    if (inString) {
      if (char === "\\" && !escaped) escaped = true;
      else {
        if (char === '"' && !escaped) inString = false;
        escaped = false;
      }
      continue;
    }
    if (char === '"') {
      inString = true;
      continue;
    }
    if (char === closing) depth += 1;
    if (char === opening) {
      depth -= 1;
      if (depth === 0) return text.slice(index, end + 1);
    }
  }
  return null;
}

function extractTruncatedObject(text: string): string | null {
  const markedOpen = text.lastIndexOf(JSON_OPEN);
  if (markedOpen >= 0) {
    const value = text.slice(markedOpen + JSON_OPEN.length).replace(JSON_CLOSE, "").trim();
    if (/^\{[\s\S]*["']?(?:title|content)["']?\s*:/i.test(value)) return value;
  }
  const match = /\{\s*["']?(?:title|content)["']?\s*:/gi;
  let start = -1;
  for (const found of text.matchAll(match)) start = found.index ?? start;
  return start >= 0 ? stripFence(text.slice(start)) : null;
}

export function extractJsonText(text: string): string {
  const candidate = extractMarked(text) ?? extractFenced(text) ?? extractBalancedObject(text) ?? extractTruncatedObject(text);
  if (!candidate) {
    throw new AdapterError(
      "JSON_ENVELOPE_NOT_FOUND",
      `模型回复中没有找到 ${JSON_OPEN}...${JSON_CLOSE}`,
      true,
    );
  }
  return stripFence(candidate);
}

function escapeRawControlCharactersInStrings(value: string): string {
  let output = "";
  let inString = false;
  let escaped = false;
  for (const char of value) {
    if (inString && !escaped) {
      if (char === "\n") { output += "\\n"; continue; }
      if (char === "\r") { output += "\\r"; continue; }
      if (char === "\t") { output += "\\t"; continue; }
    }
    output += char;
    if (char === '"' && !escaped) inString = !inString;
    if (char === "\\" && !escaped) escaped = true;
    else escaped = false;
  }
  return output;
}

export function parseJsonText(jsonText: string): unknown {
  try {
    return JSON.parse(jsonText);
  } catch (originalError) {
    try {
      return JSON.parse(escapeRawControlCharactersInStrings(jsonText));
    } catch {
      try {
        return JSON.parse(jsonrepair(jsonText));
      } catch {
        throw originalError;
      }
    }
  }
}

export function parseAndValidateJson(text: string, schema?: JsonSchema): unknown {
  const jsonText = extractJsonText(text);
  let value: unknown;
  try {
    value = parseJsonText(jsonText);
  } catch (error) {
    throw new AdapterError(
      "INVALID_MODEL_JSON",
      error instanceof Error ? error.message : "模型返回的 JSON 无法解析",
      true,
      { jsonText },
    );
  }

  if (schema) {
    let validate: ValidateFunction;
    try {
      validate = ajv.compile(schema);
    } catch (error) {
      throw new AdapterError(
        "INVALID_OUTPUT_SCHEMA",
        error instanceof Error ? error.message : "outputSchema 无效",
        false,
      );
    }
    if (!validate(value)) {
      const receivedKeys = value && typeof value === "object" && !Array.isArray(value)
        ? Object.keys(value as Record<string, unknown>)
        : [];
      throw new AdapterError(
        "MODEL_JSON_SCHEMA_MISMATCH",
        "模型 JSON 不符合 outputSchema",
        true,
        {
          validationErrors: validate.errors,
          receivedKeys,
          valuePreview: JSON.stringify(value).slice(0, 1_200),
        },
      );
    }
  }
  return value;
}
