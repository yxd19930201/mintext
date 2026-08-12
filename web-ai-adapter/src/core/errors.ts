export class AdapterError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly retryable = false,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = "AdapterError";
  }
}

export function normalizeError(error: unknown): AdapterError {
  if (error instanceof AdapterError) return error;
  if (error instanceof Error) {
    if (/locator\.|page\.|element is not visible|waiting for locator|playwright/i.test(error.message)) {
      return new AdapterError(
        "BROWSER_INTERACTION_FAILED",
        "网页控件在操作过程中发生变化，请重新检测渠道状态后重试",
        true,
      );
    }
    return new AdapterError("UNEXPECTED_ERROR", error.message, false);
  }
  return new AdapterError("UNEXPECTED_ERROR", String(error), false);
}
