import type { LinsightInfo } from '~/store/linsight';

/** Failure classification as the backend persisted it in `output_result`. */
interface PersistedFailure {
    error_code?: number;
    error_type?: string;
    detail?: string;
}

/**
 * Rebuild `taskErrorInfo` for a session version loaded from the server (page
 * refresh, history, reconcile). The live `error_message` event fills it while a
 * run is open; without this, a reloaded failure always fell back to the generic
 * "unknown" card even though `output_result` carries the precise `error_type`.
 */
export function taskErrorInfoFromOutput(
    status: string | undefined,
    outputResult: PersistedFailure | null | undefined,
): LinsightInfo['taskErrorInfo'] {
    if (status !== 'failed' || !outputResult?.error_type) return undefined;
    return {
        error_code: outputResult.error_code,
        error_type: outputResult.error_type,
        detail: outputResult.detail,
    };
}
