import i18next from "i18next";

const ASR_ERROR_CODES = new Set([10014, 10015, 10016, 10017, 10018, 10019]);

const API_ERROR_FALLBACKS: Record<number, string> = {
  10014: "未配置知识库语音转文字（ASR）模型，请在「系统模型设置 → 知识库模型」中配置后再上传音视频。",
  10015: "知识库 ASR 模型配置已被删除，请在「系统模型设置 → 知识库模型」中重新配置。",
  10016: "知识库 ASR 服务提供方已被删除，请在「系统模型设置 → 知识库模型」中重新配置。",
  10017: "知识库 ASR 模型类型不正确，请在「系统模型设置 → 知识库模型」中选择 ASR 类型模型（当前：{{model_type}}）。",
  10018: "知识库 ASR 模型「{{server_name}}/{{model_name}}」已下线，请在「系统模型设置 → 知识库模型」中更换可用模型。",
  10019: "知识库 ASR 初始化失败，请检查「系统模型设置 → 知识库模型」中的配置。错误信息：{{exception}}",
  10956: "未检测到可识别音频，无法生成识别文本。请上传包含清晰人声的音频或视频文件。",
};

function applyTemplate(template: string, data?: Record<string, unknown>): string {
  if (!data) return template;
  return template.replace(/\{\{(\w+)\}\}/g, (_, key: string) => {
    const value = data[key];
    return value === undefined || value === null ? "" : String(value);
  });
}

function translateApiError(statusCode: number, data?: Record<string, unknown>): string | undefined {
  const key = `api_errors.${statusCode}`;
  if (i18next.exists(key)) {
    return i18next.t(key, data);
  }
  const fallback = API_ERROR_FALLBACKS[statusCode];
  return fallback ? applyTemplate(fallback, data) : undefined;
}

function translateKnowledgeMedia(key: string): string | undefined {
  const fullKey = `com_knowledge.${key}`;
  if (i18next.exists(fullKey)) {
    return i18next.t(fullKey);
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

  return undefined;
}
