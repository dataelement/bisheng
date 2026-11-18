/** Trusted-browser RPC for the independent DSH PPT composer. */
import type { ConnectionRpcHandler } from '@deepseek-ai/dsh-client-connection';
import { type PptService } from './ppt-service.ts';
/** Create the state-only RPC used by the Kimi composer button and template browser. */
export declare function pptRpc(service: PptService): ConnectionRpcHandler;