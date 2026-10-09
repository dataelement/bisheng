import axios from '../request';

type CitationFailurePayload = { reason?: string; status_code?: number; data?: { reason?: string; status_code?: number } };
type CitationRequestFailure = CitationFailurePayload & { citationForbidden?: boolean; citationExpired?: boolean; response?: { data?: CitationFailurePayload } };

export interface ChatCitationItem {
    itemId?: string;
    chunkId?: string;
    chunkIndex?: number;
    documentName?: string;
    fileName?: string;
    filename?: string;
    file_name?: string;
    title?: string;
    snippet?: string;
    content?: string;
    page?: number;
    bbox?: string | null;
}

export interface ChatCitation {
    id?: number;
    messageId?: number;
    citationId: string;
    itemId?: string;
    type?: string;
    sourcePayload?: {
        items?: ChatCitationItem[];
        url?: string;
        title?: string;
        snippet?: string;
        source?: string;
        siteIcon?: string;
        datePublished?: string;
        knowledgeName?: string;
        fileType?: string;
        documentName?: string;
        previewUrl?: string;
        downloadUrl?: string;
        sourceUrl?: string;
        page?: number;
        [key: string]: unknown;
    };
    [key: string]: unknown;
}

const citationDetailMemoryCache: Record<string, ChatCitation> = {};
const citationResolveRequestCache: Record<string, Promise<ChatCitation[]>> = {};

export type CitationUnresolvedReason = "forbidden" | "expired";

const citationReasonCache: Record<string, CitationUnresolvedReason> = {};

export function getCitationUnresolvedReason(citationId: string): CitationUnresolvedReason | undefined {
    return citationReasonCache[citationId];
}

function citationReasonFromPayload(payload: CitationFailurePayload | null | undefined): CitationUnresolvedReason {
    const reason = payload?.data?.reason ?? payload?.reason;
    if (reason === "expired") {
        return "expired";
    }
    return "forbidden";
}

function throwCitationResolveError(citationId: string, payload: CitationFailurePayload | null | undefined): never {
    const reason = citationReasonFromPayload(payload);
    citationReasonCache[citationId] = reason;
    const err = Object.assign(new Error(reason === "expired" ? "citation expired" : "citation forbidden"), {
        citationForbidden: reason !== "expired",
        citationExpired: reason === "expired",
    });
    throw err;
}

export async function getCitationDetail(citationId: string): Promise<ChatCitation> {
    if (citationDetailMemoryCache[citationId]) {
        return citationDetailMemoryCache[citationId];
    }

    try {
        const detail = await axios.get<unknown, ChatCitation & CitationFailurePayload>(
            `/api/v1/citations/${encodeURIComponent(citationId)}`,
            { silent: true },
        );
        if (detail?.status_code === 404) {
            throwCitationResolveError(citationId, detail);
        }
        if (detail?.citationId) {
            citationDetailMemoryCache[detail.citationId] = detail;
            delete citationReasonCache[detail.citationId];
        }
        citationDetailMemoryCache[citationId] = detail;
        return detail;
    } catch (caught) {
        const error = caught as CitationRequestFailure | null | undefined;
        if (error?.citationForbidden || error?.citationExpired) {
            throw error;
        }
        const status = error?.status_code || error?.response?.data?.status_code;
        if (status === 404) {
            throwCitationResolveError(citationId, error?.response?.data ?? error);
        }
        throw error;
    }
}

export async function resolveCitationDetails(citationIds: string[]): Promise<ChatCitation[]> {
    const uniqueCitationIds = Array.from(new Set(
        citationIds.filter((citationId) => citationId && !citationId.startsWith("citation:")),
    )).filter((citationId) => !citationDetailMemoryCache[citationId]);

    if (!uniqueCitationIds.length) {
        return citationIds
            .map((citationId) => citationDetailMemoryCache[citationId])
            .filter(Boolean);
    }

    const requestKey = uniqueCitationIds.sort().join("|");
    const pendingRequest = citationResolveRequestCache[requestKey];
    const resolvedItems = pendingRequest
        ? await pendingRequest
        : await (citationResolveRequestCache[requestKey] = axios.post<unknown, { items?: ChatCitation[]; unresolved?: { citationId?: string; reason?: string }[] }>(
            `/api/v1/citations/resolve`,
            {
                citationIds: uniqueCitationIds,
            },
            { silent: true },
        ).then((response) => {
            const items = Array.isArray(response?.items) ? response.items : [];
            items.forEach((detail) => {
                if (detail?.citationId) {
                    citationDetailMemoryCache[detail.citationId] = detail;
                    delete citationReasonCache[detail.citationId];
                }
            });
            const unresolved = Array.isArray(response?.unresolved) ? response.unresolved : [];
            unresolved.forEach((entry) => {
                if (entry?.citationId && (entry.reason === "expired" || entry.reason === "forbidden")) {
                    citationReasonCache[entry.citationId] = entry.reason;
                }
            });
            return items;
        }).finally(() => {
            delete citationResolveRequestCache[requestKey];
        }));

    return citationIds
        .map((citationId) => citationDetailMemoryCache[citationId])
        .filter(Boolean)
        .concat(resolvedItems.filter((detail) => detail?.citationId && !citationIds.includes(detail.citationId)));
}
