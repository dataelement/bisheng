type LocalizeFn = (key: string, options?: Record<string, unknown>) => string;

const WEB_LINK_ERROR_KEY_MAP: Record<string, string> = {
    "web link redirect location is missing": "com_knowledge.web_link_request_failed",
    "web link content type is not supported": "com_knowledge.web_link_content_type_unsupported",
    "web link content is too large": "com_knowledge.web_link_content_too_large",
    "web link redirects too many times": "com_knowledge.web_link_redirects_too_many",
    "web link content is empty": "com_knowledge.web_link_content_empty",
    "web link url is empty": "com_knowledge.web_link_url_required",
    "only http/https web links are supported": "com_knowledge.web_link_http_only",
    "web link host is missing": "com_knowledge.web_link_invalid",
    "this web link host is not allowed": "com_knowledge.web_link_host_not_allowed",
    "this web link address is not allowed": "com_knowledge.web_link_address_not_allowed",
    "web link host cannot be resolved": "com_knowledge.web_link_host_unresolved",
};

const MEDIA_ERROR_KEY_MAP: Record<string, string> = {
    "media file does not exist": "com_knowledge.media_file_missing",
    "asr returned empty text": "com_knowledge.media_asr_empty",
    "no recognizable audio detected": "com_knowledge.media_no_recognizable_audio",
    "asr api key is missing": "com_knowledge.media_asr_api_key_missing",
    "ffmpeg is not installed": "com_knowledge.media_ffmpeg_missing",
    "media audio extraction failed": "com_knowledge.media_audio_extraction_failed",
};

function translateIfExists(localize: LocalizeFn, key: string, options?: Record<string, unknown>) {
    const value = localize(key, options);
    return value && value !== key ? value : "";
}

function resolveKnownErrorKey(message: string) {
    const normalized = message.trim().toLowerCase();
    if (!normalized) return "";
    if (normalized.startsWith("web link request failed")) {
        return "com_knowledge.web_link_request_failed";
    }
    if (normalized.startsWith("knowledge media transcription only supports aliyun/qwen asr")) {
        return "com_knowledge.media_asr_provider_unsupported";
    }
    if (normalized.startsWith("asr request failed")) {
        return "com_knowledge.media_asr_request_failed";
    }
    return WEB_LINK_ERROR_KEY_MAP[normalized] || MEDIA_ERROR_KEY_MAP[normalized] || "";
}

export function resolveLocalizedKnowledgeImportError(
    error: any,
    localize: LocalizeFn,
    fallbackKey: string,
) {
    const statusCode = error?.status_code ?? error?.statusCode;
    const errorData = error?.data ?? error?.errorData ?? {};
    const rawMessage = (
        typeof error?.status_message === "string" && error.status_message
            ? error.status_message
            : typeof error?.message === "string"
                ? error.message
                : ""
    ).trim();

    if (rawMessage) {
        const translatedByExactMessage = translateIfExists(localize, `api_errors.${rawMessage}`, errorData);
        if (translatedByExactMessage) return translatedByExactMessage;

        const knownKey = resolveKnownErrorKey(rawMessage);
        if (knownKey) {
            const translatedByKnownKey = translateIfExists(localize, knownKey, errorData);
            if (translatedByKnownKey) return translatedByKnownKey;
        }
    }

    if (statusCode !== undefined && statusCode !== null) {
        const translated = translateIfExists(localize, `api_errors.${statusCode}`, errorData);
        if (translated) return translated;
    }

    return localize(fallbackKey);
}
