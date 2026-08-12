import type {
  GenerateRequest,
  ResolvedExecutionMode,
  TaskType,
} from "../contracts.js";

const fastTasks = new Set<TaskType>([
  "summary",
  "state_extract",
  "metadata",
  "json_transform",
]);

const qualityTasks = new Set<TaskType>([
  "novel_design",
  "outline",
  "chapter_draft",
  "chapter_rewrite",
  "continuity_review",
  "quality_review",
]);

const qualityKeywords = /小说|正文|章节|续写|重写|大纲|分卷|世界观|人物弧|伏笔|连续性|审稿|钩子|文风/;

export function resolveExecutionMode(request: GenerateRequest): ResolvedExecutionMode {
  if (request.mode && request.mode !== "auto") return request.mode;
  if (request.taskType && qualityTasks.has(request.taskType)) return "quality";
  if (request.taskType && fastTasks.has(request.taskType)) return "fast";
  if (qualityKeywords.test(request.instruction ?? "")) return "quality";
  // 未知任务宁可多思考，避免为了速度牺牲正文质量。
  return "quality";
}
