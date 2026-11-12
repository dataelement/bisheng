/** Typed browser wrapper over the dedicated Office PPT Connection channel. */
import type { ClientConnectionRpc } from '@deepseek-ai/dsh-client-connection/client';
import type { SessionId } from '@deepseek-ai/dsh-client-runtime/client';
/** Session-bound Office PPT client used by the view. */
export interface OfficePptClient {
    call<T>(endpoint: string, payload?: Record<string, unknown>, signal?: AbortSignal): Promise<T>;
}
/** Decode canonical base64 content without creating a browser URL. */
export declare function decodeBase64(contentBase64: string): Uint8Array<ArrayBuffer>;
/**
 * Bind every request to the active conversation session.
 * @param rpc - Browser Connection RPC client.
 * @param sessionId - Active conversation session.
 * @returns Session-bound Office PPT client.
 */
export declare function createOfficePptClient(rpc: ClientConnectionRpc, sessionId: SessionId): OfficePptClient;
/**
 * Download one trusted-Host RPC result in the browser.
 * @param fileName - Browser download name.
 * @param mediaType - Blob media type.
 * @param contentBase64 - Canonical base64 file content.
 */
export declare function downloadBase64(fileName: string, mediaType: string, contentBase64: string): void;