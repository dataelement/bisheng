import { localizedBusinessFailure, requestFailureMetadata, type FailureInfo } from '~/utils/failureInfo';

export interface PendingSubmitFailure {
    message: string;
    failureInfo?: FailureInfo;
    errorCode?: number;
}

/** Only known numeric business codes may supply display copy. */
export function resolveLinsightSubmitFailure(
    error: unknown,
    localize: (key: string, values?: object) => string,
    fallbackKey: string,
) {
    const metadata = requestFailureMetadata(error);
    const raw = error && typeof error === 'object' ? error as Record<string, unknown> : undefined;
    const response = raw?.response && typeof raw.response === 'object' ? raw.response as Record<string, unknown> : undefined;
    const envelope = response?.data && typeof response.data === 'object' ? response.data as Record<string, unknown> : raw;
    const businessMessage = localizedBusinessFailure(metadata?.error_code, localize, envelope?.data);
    const failure: PendingSubmitFailure = {
        message: businessMessage || localize(fallbackKey),
        failureInfo: metadata?.failure_info,
        errorCode: metadata?.error_code,
    };
    return { failure, metadata, businessMessage };
}
