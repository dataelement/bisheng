/** Session-confined persistence for the DSH PPTD route. */
import type { SessionId } from '@deepseek-ai/dsh-session/types';
import type { OfficeActivity, OfficeDeck, OfficePptState } from './protocol.ts';
/** Storage ceilings used by the PPT route. */
export interface KimiStoreLimits {
    readonly maxDecksPerSession: number;
    readonly maxActivities: number;
}
/** DSH PPTD-compatible source published beside the editable PPTX. */
export interface PptdProjectFiles {
    readonly pptdEntryName: string;
    readonly pptdManifest: string;
    readonly pptdPages: readonly {
        readonly path: string;
        readonly content: string;
    }[];
    readonly assets: readonly {
        readonly path: string;
        readonly bytes: Uint8Array;
    }[];
}
/** Local store containing only PPT route state, source projects, and output files. */
export declare class PptStore {
    private readonly limits;
    readonly root: string;
    private auditTail;
    constructor(root: string, limits: KimiStoreLimits);
    private sessionDirectory;
    private statePath;
    readState(sessionId: SessionId): Promise<OfficePptState>;
    assertDeckCapacity(state: OfficePptState): void;
    writeState(state: OfficePptState): Promise<void>;
    writeOutput(sessionId: SessionId, deck: Pick<OfficeDeck, 'id' | 'title' | 'revision'>, bytes: Uint8Array, workspaceRoot: string, project: PptdProjectFiles, requestedFileName: string): Promise<{
        readonly storageKey: string;
        readonly fileName: string;
        readonly workspaceDirectoryPath: string;
        readonly workspaceFilePath: string;
    }>;
    appendAudit(sessionId: SessionId, activity: OfficeActivity, facts: {
        readonly deckId?: string;
        readonly templateId?: string;
        readonly mode?: string;
    }): Promise<void>;
    private publishWorkspaceOutput;
    private writeFile;
    private writeProjectFile;
}