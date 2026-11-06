import { resolveErrorMessageTemplate } from '@bisheng/api-client';
import i18next from "i18next";

const ASR_ERROR_CODES = new Set([10014, 10015, 10016, 10017, 10018, 10019]);

function translateApiError(statusCode: number, data?: Record<string, unknown>): string | undefined {
  const key = `api_errors.${statusCode}` as `api_errors.${keyof typeof import('../locales/en/api_errors.gen.json')}`;
  if (!i18next.exists(key)) return undefined;
  return resolveErrorMessageTemplate(String(i18next.t(key)), data, String(i18next.t('api_errors.fallback')));
}

function translateKnowledgeMedia(key: "media_asr_api_key_missing" | "media_asr_provider_unsupported" | "media_asr_request_failed" | "media_no_recognizable_audio"): string | undefined {
  const fullKey = `com_knowledge.${key}` as const;
  if (i18next.exists(fullKey)) {
    return String(i18next.t(fullKey));
  }
  return undefined;
}

function resolve10954Message(parsed: Record<string, unknown>, errorData: Record<string, unknown>): string | undefined {
  const statusMessage = String(
    parsed.status_message ?? parsed.message ?? errorData.exception ?? "",
  ).toLowerCase();

  if (statusMessage.includes("api key is missing")) {
    return translateKnowledgeMedia("media_asr_api_key_missing");
  }
  if (
    statusMessage.includes("only supports aliyun/qwen")
    || statusMessage.includes("knowledge media transcription only supports")
    || statusMessage.includes("does not support asr provider")
  ) {
    return translateKnowledgeMedia("media_asr_provider_unsupported");
  }
  if (statusMessage.includes("asr request failed")) {
    return translateKnowledgeMedia("media_asr_request_failed");
  }
  return translateApiError(10954, errorData);
}

/** Resolve knowledge file parse failure messages, including knowledge-base ASR errors. */
export function resolveKnowledgeParseFailureMessage(parsed: Record<string, unknown>): string | undefined {
  const statusCode = Number(parsed.status_code ?? parsed.code);
  if (!Number.isFinite(statusCode)) {
    return undefined;
  }

  const errorData = (parsed.data && typeof parsed.data === "object"
    ? parsed.data
    : {}) as Record<string, unknown>;

  if (statusCode === 10956) {
    return translateApiError(10956, errorData)
      ?? translateKnowledgeMedia("media_no_recognizable_audio");
  }

  const exception = String(errorData.exception ?? "").trim().toLowerCase();
  if (exception === "media audio extraction failed" || exception === "asr returned empty text") {
    return translateApiError(10956, errorData)
      ?? translateKnowledgeMedia("media_no_recognizable_audio");
  }

  if (ASR_ERROR_CODES.has(statusCode)) {
    return translateApiError(statusCode, errorData);
  }

  if (statusCode === 10954) {
    return resolve10954Message(parsed, errorData);
  }

  return translateApiError(statusCode, errorData);
}
