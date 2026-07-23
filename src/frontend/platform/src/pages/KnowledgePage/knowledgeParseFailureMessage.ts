type TranslateFn = (key: string, options?: Record<string, unknown>) => string;

const ASR_ERROR_CODES = new Set([10014, 10015, 10016, 10017, 10018, 10019]);

function getErrorData(input: Record<string, unknown>): Record<string, unknown> {
  const nested = input.data;
  if (nested && typeof nested === "object" && !Array.isArray(nested)) {
    return { ...(nested as Record<string, unknown>) };
  }
  return {
    exception: input.exception,
    model_type: input.model_type,
    server_name: input.server_name,
    model_name: input.model_name,
  };
}

function normalizeInput(input: unknown): Record<string, unknown> | null {
  if (!input) return null;
  if (typeof input === "string") {
    const trimmed = input.trim();
    if (!trimmed) return null;
    if (!trimmed.startsWith("{")) {
      return { message: trimmed };
    }
    try {
      return JSON.parse(trimmed) as Record<string, unknown>;
    } catch {
      return { message: trimmed };
    }
  }
  if (typeof input === "object") {
    return input as Record<string, unknown>;
  }
  return null;
}

function resolve10954Message(
  parsed: Record<string, unknown>,
  errorData: Record<string, unknown>,
  t: TranslateFn,
): string {
  const statusMessage = String(
    parsed.status_message ?? parsed.message ?? errorData.exception ?? "",
  ).toLowerCase();

  if (statusMessage.includes("api key is missing")) {
    return t("mediaAsrApiKeyMissing", { ns: "knowledge" });
  }
  if (
    statusMessage.includes("only supports aliyun/qwen")
    || statusMessage.includes("knowledge media transcription only supports")
  ) {
    return t("mediaAsrProviderUnsupported", { ns: "knowledge" });
  }
  if (statusMessage.includes("asr request failed")) {
    return t("mediaAsrRequestFailed", { ns: "knowledge" });
  }
  return t("api_errors:10954", errorData);
}

/** Resolve knowledge file parse failure messages, including knowledge-base ASR errors. */
export function resolveKnowledgeParseFailure(input: unknown, t: TranslateFn): string | undefined {
  const parsed = normalizeInput(input);
  if (!parsed) return undefined;

  if (typeof parsed.message === "string" && !parsed.status_code && !parsed.code) {
    const known = resolveKnownExceptionMessage(parsed.message, t);
    if (known) return known;
  }

  const statusCode = Number(parsed.status_code ?? parsed.code);
  if (!Number.isFinite(statusCode)) {
    return typeof parsed.message === "string" ? parsed.message : undefined;
  }

  const errorData = getErrorData(parsed);

  if (statusCode === 10956) {
    return t("mediaNoRecognizableAudio", { ns: "knowledge" });
  }

  const exception = String(errorData.exception ?? "").trim().toLowerCase();
  if (exception === "media audio extraction failed" || exception === "asr returned empty text") {
    return t("mediaNoRecognizableAudio", { ns: "knowledge" });
  }

  if (ASR_ERROR_CODES.has(statusCode)) {
    return t(`api_errors:${statusCode}`, errorData);
  }

  if (statusCode === 10954) {
    return resolve10954Message(parsed, errorData, t);
  }

  const translated = t(`api_errors:${statusCode}`, errorData);
  if (translated && translated !== `api_errors:${statusCode}`) {
    return translated;
  }

  return undefined;
}

function resolveKnownExceptionMessage(message: string, t: TranslateFn): string | undefined {
  const normalized = message.trim().toLowerCase();
  if (!normalized) return undefined;

  if (normalized.includes("api key is missing")) {
    return t("mediaAsrApiKeyMissing", { ns: "knowledge" });
  }
  if (normalized.includes("knowledge media transcription only supports")) {
    return t("mediaAsrProviderUnsupported", { ns: "knowledge" });
  }
  if (normalized.includes("asr request failed")) {
    return t("mediaAsrRequestFailed", { ns: "knowledge" });
  }
  if (normalized === "media audio extraction failed" || normalized === "asr returned empty text") {
    return t("mediaNoRecognizableAudio", { ns: "knowledge" });
  }
  return undefined;
}
