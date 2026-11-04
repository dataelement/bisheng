type CitationEnvelope = {
    status_code?: number;
    reason?: string;
    data?: { reason?: string };
};

export type CitationFailure = CitationEnvelope & {
    response?: { data?: CitationEnvelope };
    citationForbidden?: boolean;
    citationExpired?: boolean;
};

function recordOf(value: unknown): Record<string, unknown> {
    return typeof value === "object" && value !== null
        ? value as Record<string, unknown> : {};
}

function readEnvelope(value: unknown): CitationEnvelope {
    const record = recordOf(value);
    const data = recordOf(record.data);
    return {
        status_code: typeof record.status_code === "number" ? record.status_code : undefined,
        reason: typeof record.reason === "string" ? record.reason : undefined,
        data: { reason: typeof data.reason === "string" ? data.reason : undefined },
    };
}

export function readCitationFailure(value: unknown): CitationFailure {
    if (typeof value !== "object" || value === null) return {};
    const record = recordOf(value);
    const responseData = recordOf(record.response).data;
    return {
        ...readEnvelope(value),
        response: responseData == null ? undefined : { data: readEnvelope(responseData) },
        citationForbidden: record.citationForbidden === true,
        citationExpired: record.citationExpired === true,
    };
}
