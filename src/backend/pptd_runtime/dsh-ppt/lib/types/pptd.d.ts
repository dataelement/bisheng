/** Local PPTD v2 parser, checker, loader, and native editable PPTX renderer. */
import type { OfficeTemplatePageRelationship } from './protocol.ts';
type Dict = Record<string, unknown>;
/** One in-memory local resource available to a PPTD project. */
export interface PptdAsset {
    readonly path: string;
    readonly mediaType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp' | 'image/svg+xml';
    readonly bytes: Uint8Array;
    readonly sha256: string;
}
/** Multi-file PPTD source plane. Paths are project-root-relative. */
export interface PptdProjectSource {
    readonly entryName: string;
    readonly manifest: string;
    readonly pages: ReadonlyMap<string, string>;
    readonly assets: ReadonlyMap<string, PptdAsset>;
    readonly issues?: readonly PptdIssue[];
}
/** One normalized PPTD diagnostic. */
export interface PptdIssue {
    readonly code: string;
    readonly severity: 'warning' | 'error';
    readonly message: string;
    readonly file?: string;
    readonly page?: number;
    readonly elementId?: string;
}
/** Deterministic evidence returned by the PPTD checker. */
export interface PptdCheck {
    readonly status: 'pass' | 'warning' | 'fail';
    readonly digest: string;
    readonly pageCount: number;
    readonly nativeObjectCount: number;
    readonly warningCount: number;
    readonly errorCount: number;
    readonly issues: readonly PptdIssue[];
    readonly compatibility: PptdCompatibilitySummary;
}
/** Renderer outcome promised for one PPTD semantic feature. */
export type PptdCompatibilityLevel = 'native' | 'normalized' | 'vector-fallback' | 'raster-fallback' | 'unsupported';
/** Aggregate renderer compatibility included in every deterministic check. */
export interface PptdCompatibilitySummary {
    readonly native: number;
    readonly normalized: number;
    readonly vectorFallback: number;
    readonly rasterFallback: number;
    readonly unsupported: number;
}
/** Parsed PPTD project retained as a normalized, renderer-independent AST. */
export interface PptdProject {
    readonly source: PptdProjectSource;
    readonly title: string;
    readonly width: number;
    readonly height: number;
    readonly template?: Dict;
    readonly theme: Dict;
    readonly pages: readonly PptdPage[];
    readonly parseIssues: readonly PptdIssue[];
}
/** One parsed PPTD page. */
export interface PptdPage {
    readonly file: string;
    readonly pageType?: string;
    readonly templateReference?: {
        readonly sourceSlideNumber: number;
        readonly rationale: string;
        readonly contentRelationship?: OfficeTemplatePageRelationship;
    };
    readonly background?: Dict;
    readonly notes: string;
    readonly elements: readonly Dict[];
}
/** Native editable PPTX generated from a checked PPTD AST. */
export interface RenderedPptd {
    readonly bytes: Uint8Array;
    readonly nativeObjectCount: number;
    readonly check: PptdCheck;
}
/** Parse a bounded in-memory PPTD v2 project into a renderer-independent AST. */
export declare function parsePptdProject(source: PptdProjectSource): PptdProject;
/** Check structure, renderability, and measurable composition signals without external effects. */
export declare function checkPptdProject(project: PptdProject): PptdCheck;
/** Render one checked PPTD AST to editable native PowerPoint objects. */
export declare function renderPptdProject(project: PptdProject): Promise<RenderedPptd>;
/** Resolve a PPTD entry file from either the entry itself or its project directory. */
export declare function resolvePptdEntry(inputPath: string): Promise<string>;
/** Load a confined local PPTD project. Network resources stay disabled. */
export declare function loadPptdProject(entryPath: string): Promise<PptdProject>;
export {};