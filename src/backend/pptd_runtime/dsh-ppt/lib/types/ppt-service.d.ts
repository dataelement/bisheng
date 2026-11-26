/** Application service for the independent DSH PPTD route. */
import type { SessionId } from '@deepseek-ai/dsh-session/types';
import { type PptdProject } from './pptd.ts';
import { type OfficeDeck, type OfficePptState, type OfficeTemplate, type OfficeTemplatePageReference } from './protocol.ts';
import { PptStore } from './ppt-store.ts';
/** Host-side limits for direct PPTD rendering. */
export interface PptLimits {
    readonly maxSlides: number;
}
/** Attributed caller crossing the browser or model boundary. */
export interface PptActor {
    readonly kind: 'user' | 'agent';
}
/** Error with a stable RPC-facing business category. */
export declare class PptError extends Error {
    readonly code: 'invalid-request' | 'not-found' | 'conflict' | 'unsupported' | 'limit-exceeded' | 'operation-failed';
    constructor(code: 'invalid-request' | 'not-found' | 'conflict' | 'unsupported' | 'limit-exceeded' | 'operation-failed', message: string);
}
/** Complete local workflow for the Kimi composer, browser state, and model tools. */
export declare class PptService {
    private readonly store;
    private readonly limits;
    private readonly locks;
    constructor(store: PptStore, limits: PptLimits);
    state(sessionId: SessionId): Promise<OfficePptState>;
    templatePages(sessionId: SessionId, templateId: string, slideNumbers?: readonly number[]): Promise<readonly OfficeTemplatePageReference[]>;
    selectTemplate(sessionId: SessionId, templateId: string, actor: PptActor): Promise<OfficeTemplate>;
    selectPresentationMode(sessionId: SessionId, active: boolean, actor: PptActor): Promise<boolean>;
    selectDocumentMode(sessionId: SessionId, mode: 'word' | 'excel' | null, actor: PptActor): Promise<boolean>;
    selectDocumentTemplate(sessionId: SessionId, template: { id: string; mode: 'word' | 'excel'; revision: string }, actor: PptActor): Promise<boolean>;
    deselectDocumentTemplate(sessionId: SessionId, actor: PptActor): Promise<boolean>;
    deselectTemplate(sessionId: SessionId, actor: PptActor): Promise<boolean>;
    createPptdDeck(sessionId: SessionId, project: PptdProject, requestedFileName: string, workspaceRoot: string, actor: PptActor, signal: AbortSignal): Promise<OfficeDeck>;
    private mutate;
    private activity;
    private withLock;
}