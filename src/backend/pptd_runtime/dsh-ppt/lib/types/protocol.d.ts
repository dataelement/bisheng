/** Browser-safe Office PPT request and result types. */
import type { Branded } from '@deepseek-ai/dsh-brand';
import type { SessionId } from '@deepseek-ai/dsh-session/types';
/** Opaque presentation identity. */
export type OfficeDeckId = Branded<'OfficeDeckId'>;
/** Opaque slide identity stable across revisions. */
export type OfficeSlideId = Branded<'OfficeSlideId'>;
/** Opaque template identity. */
export type OfficeTemplateId = Branded<'OfficeTemplateId'>;
/** Opaque operation identity in the presentation activity ledger. */
export type OfficeActivityId = Branded<'OfficeActivityId'>;
/**
 * Brand a validated presentation id.
 * @param value - Validated identifier text.
 * @returns Presentation identity.
 */
export declare function OfficeDeckId(value: string): OfficeDeckId;
/**
 * Brand a validated slide id.
 * @param value - Validated identifier text.
 * @returns Slide identity.
 */
export declare function OfficeSlideId(value: string): OfficeSlideId;
/**
 * Brand a validated template id.
 * @param value - Validated identifier text.
 * @returns Template identity.
 */
export declare function OfficeTemplateId(value: string): OfficeTemplateId;
/**
 * Brand a validated activity id.
 * @param value - Validated identifier text.
 * @returns Activity identity.
 */
export declare function OfficeActivityId(value: string): OfficeActivityId;
/** Template colors used by both native generation and browser previews. */
export interface OfficePalette {
    readonly background: string;
    readonly surface: string;
    readonly text: string;
    readonly muted: string;
    readonly accent: string;
    readonly secondary: string;
}
/** Bounded native layout family inferred from one or more uploaded source slides. */
export type OfficeTemplateLayoutFamily = 'cover' | 'statement' | 'single-column' | 'two-column' | 'grid' | 'data' | 'image-led';
/** Existing renderer grammar selected from uploaded layout and typography evidence. */
export type OfficeTemplateVisualGrammar = 'blue-professional' | 'editorial-forest' | 'signal' | 'orange-data';
/** Aggregated source-slide geometry used to explain and guide native generation. */
export interface OfficeTemplateLayoutPattern {
    readonly family: OfficeTemplateLayoutFamily;
    readonly slideCount: number;
    readonly sampleSlideNumbers: readonly number[];
    readonly titlePosition: 'top' | 'center' | 'left' | 'right';
    readonly bodyColumns: 0 | 1 | 2 | 3;
    readonly density: OfficeDesignSpec['density'];
    readonly averageTextFrames: number;
    readonly averageMediaFrames: number;
}
/** Semantic source-page feature used to match content jobs to uploaded template pages. */
export type OfficeTemplatePageFeature = 'chart' | 'table' | 'image' | 'timeline' | 'process' | 'comparison' | 'matrix' | 'kpi' | 'statement';
/** Content relationship expressed by one source page or requested output page. */
export type OfficeTemplatePageRelationship = 'statement' | 'independent' | 'comparison' | 'process' | 'timeline' | 'overlap' | 'data' | 'generic';
/** Whether the source geometry can be executed directly by the generated structure reference. */
export type OfficeTemplateReferenceFidelity = 'executable' | 'visual-reference';
/** One normalized editable region retained from an uploaded source page. */
export interface OfficeTemplatePageZone {
    readonly kind: 'title' | 'text' | 'shape' | 'line' | 'chart' | 'table' | 'image';
    readonly x: number;
    readonly y: number;
    readonly width: number;
    readonly height: number;
    readonly shape?: 'rect' | 'roundRect' | 'ellipse' | 'line' | 'other';
    /** Original OOXML preset retained when the normalized shape category is `other`. */
    readonly presetShape?: string;
    readonly rotation?: number;
    readonly flipHorizontal?: boolean;
    readonly flipVertical?: boolean;
    readonly adjustments?: Readonly<Record<string, number>>;
    readonly fill?: string;
    readonly stroke?: string;
    readonly textRole?: 'title' | 'text';
    readonly textColor?: string;
    readonly backgroundFill?: string;
    readonly fontFace?: string;
    readonly fontSize?: number;
    readonly fontWeight?: 'normal' | 'bold';
    readonly textAlign?: 'left' | 'center' | 'right';
    /** Conservative full-width character budget derived from the region geometry and font size. */
    readonly textCapacity?: number;
}
/** Dominant source-page visual whose type, placement, and scale establish the page hierarchy. */
export interface OfficeTemplatePrimaryVisual {
    readonly kind: 'chart' | 'table' | 'image' | 'shape';
    readonly x: number;
    readonly y: number;
    readonly width: number;
    readonly height: number;
    readonly areaRatio: number;
}
/** Page-specific adaptation advice for one source-template page. */
export interface OfficeTemplatePageSimplification {
    readonly instruction: string;
}
/** Per-page semantic index and editable layout reference derived from a source presentation. */
export interface OfficeTemplatePageReference {
    readonly slideNumber: number;
    readonly sourceTitle: string;
    readonly family: OfficeTemplateLayoutFamily;
    readonly titlePosition: OfficeTemplateLayoutPattern['titlePosition'];
    readonly bodyColumns: OfficeTemplateLayoutPattern['bodyColumns'];
    readonly density: OfficeDesignSpec['density'];
    readonly features: readonly OfficeTemplatePageFeature[];
    readonly recommendedRoles: readonly OfficeSlideRole[];
    readonly relationship?: OfficeTemplatePageRelationship;
    readonly referenceFidelity?: OfficeTemplateReferenceFidelity;
    readonly structureSummary: string;
    readonly zones: readonly OfficeTemplatePageZone[];
    readonly primaryVisual?: OfficeTemplatePrimaryVisual;
    readonly simplification?: OfficeTemplatePageSimplification;
    readonly jsxReference: string;
}
/** Source facts retained for an uploaded PPTX-derived template. */
export interface OfficeTemplateSource {
    readonly fileName: string;
    readonly sha256: string;
    readonly slideCount: number;
    readonly averageTextBlocks: number;
    readonly averageCharacters: number;
    readonly visualGrammar: OfficeTemplateVisualGrammar;
    readonly recommendedDensity: OfficeDesignSpec['density'];
    readonly designSummary: string;
    readonly layoutPatterns: readonly OfficeTemplateLayoutPattern[];
    readonly pageReferences: readonly OfficeTemplatePageReference[];
    readonly extractedAt: string;
}
/** Presentation workflow that owns the selected template and authoring format. */
export type OfficePresentationMode = 'ppt';
/** Product-facing category retained from the Kimi design-system library. */
export type OfficeTemplateCategory = 'strategy' | 'business' | 'work' | 'promotion' | 'academic' | 'consulting' | 'finance' | 'custom' | 'personal';
/** Selectable presentation theme, page references, and model-facing visual guidance. */
export interface OfficeTemplate {
    readonly templateSamples?: import('./personal-template-samples.js').PersonalTemplateSamples;
    readonly templateProfile?: import('./personal-template-profile.js').PersonalTemplateProfile;
    readonly id: OfficeTemplateId;
    readonly name: string;
    readonly description: string;
    /** Deck-level color roles that remain authoritative while adapting individual source pages. */
    readonly colorGuidance?: string;
    readonly origin: 'built-in' | 'extracted' | 'personal';
    /** Explicit workflow availability. Older persisted templates default to both modes. */
    readonly supportedModes?: readonly OfficePresentationMode[];
    readonly category?: OfficeTemplateCategory;
    readonly sourceCollection?: 'indexed' | 'curated' | 'extracted';
    readonly variantLabel?: string;
    readonly aspectRatio: 'wide' | 'standard';
    readonly titleFontFace: string;
    readonly bodyFontFace: string;
    readonly palette: OfficePalette;
    readonly previewTitle: string;
    readonly previewSubtitle: string;
    readonly source?: OfficeTemplateSource;
    readonly previewImages?: readonly string[];
    readonly slideCount?: number;
    readonly createdAt?: string;
    readonly updatedAt?: string;
    readonly sha256?: string;
    readonly pageIndex?: readonly { slideNumber: number; file: string }[];
    readonly diagnostics?: readonly { slide: number; feature: string; level: string; message: string }[];
    /** Source objects retained as replaceable image slots at their original geometry. */
    readonly resourcePlaceholders?: readonly { slide: number; feature: string; elementId: string; message: string; bounds: readonly [number, number, number, number] }[];
}
/**
 * Resolve workflow availability while preserving compatibility with older extracted templates.
 * @param template - Persisted or built-in template definition.
 * @param mode - Presentation workflow requesting the template.
 * @returns Whether the template is available to the requested workflow.
 */
export declare function templateSupportsMode(template: OfficeTemplate, mode: OfficePresentationMode): boolean;
/** Narrative role performed by one slide in the deck. */
export type OfficeSlideRole = 'cover' | 'agenda' | 'section' | 'overview' | 'evidence' | 'timeline' | 'matrix' | 'comparison' | 'process' | 'closing';
/** Registered native layout identity. */
export type OfficeLayoutId = 'cover.hero' | 'agenda.simple' | 'section.statement' | 'overview.kpi' | 'data.chart-insight' | 'history.timeline' | 'product.matrix' | 'comparison.two-column' | 'process.steps' | 'closing.summary';
/** Legacy layout hint accepted at the input boundary during migration. */
export type OfficeLayoutHint = OfficeLayoutId | 'cover' | 'section' | 'content';
/** Shared template identity selected for the deterministic PPT scene compiler. */
export type OfficePptSceneVisualSystem = OfficeTemplateId;
/** One workspace image admitted by the Host and referenced by scene elements. */
export interface OfficePptSceneAsset {
    readonly id: string;
    readonly sourcePath: string;
}
/** Shared editable geometry for one scene element, measured in PowerPoint inches. */
export interface OfficePptSceneFrame {
    readonly x: number;
    readonly y: number;
    readonly width: number;
    readonly height: number;
}
/** Editable text box in a deterministic PPT scene. */
export interface OfficePptSceneTextElement extends OfficePptSceneFrame {
    readonly id: string;
    readonly kind: 'text';
    readonly text: string;
    readonly fontSize: number;
    readonly fontFace?: string;
    readonly color: string;
    readonly bold?: boolean;
    readonly align?: 'left' | 'center' | 'right';
    readonly verticalAlign?: 'top' | 'middle' | 'bottom';
    readonly collision?: boolean;
}
/** Editable native PowerPoint shape in a deterministic PPT scene. */
export interface OfficePptSceneShapeElement extends OfficePptSceneFrame {
    readonly id: string;
    readonly kind: 'shape';
    readonly shape: 'rect' | 'roundRect' | 'ellipse' | 'line';
    readonly fill?: string;
    readonly stroke?: string;
    readonly strokeWidth?: number;
    readonly radius?: number;
    readonly collision?: boolean;
}
/** Editable workspace-backed image in a deterministic PPT scene. */
export interface OfficePptSceneImageElement extends OfficePptSceneFrame {
    readonly id: string;
    readonly kind: 'image';
    readonly assetId: string;
    readonly alt: string;
    readonly collision?: boolean;
}
/** One native chart series in a deterministic PPT scene. */
export interface OfficePptSceneChartSeries {
    readonly name: string;
    readonly labels: readonly string[];
    readonly values: readonly number[];
}
/** Editable native chart in a deterministic PPT scene. */
export interface OfficePptSceneChartElement extends OfficePptSceneFrame {
    readonly id: string;
    readonly kind: 'chart';
    readonly chart: 'bar' | 'column' | 'line' | 'pie' | 'doughnut';
    readonly series: readonly OfficePptSceneChartSeries[];
    readonly colors?: readonly string[];
    readonly showLegend?: boolean;
    readonly showValues?: boolean;
    readonly collision?: boolean;
}
/** One editable element accepted by the self-owned PPT compiler. */
export type OfficePptSceneElement = OfficePptSceneTextElement | OfficePptSceneShapeElement | OfficePptSceneImageElement | OfficePptSceneChartElement;
/** One page in the declarative scene, including semantic fallback content. */
export interface OfficePptScenePage {
    readonly id: string;
    readonly role: OfficeSlideRole;
    readonly layout: OfficeLayoutId;
    readonly title: string;
    readonly bullets: readonly string[];
    readonly notes: string;
    readonly sourceRefs: readonly string[];
    /** Legacy page-level source binding retained for persisted scene compatibility. */
    readonly templateReference?: {
        readonly sourceSlideNumber: number;
        readonly rationale: string;
        readonly contentRelationship?: OfficeTemplatePageRelationship;
    };
    readonly background: string;
    readonly elements: readonly OfficePptSceneElement[];
}
/** Complete declarative input for the independent PPT mode. */
export interface OfficePptSceneInput {
    readonly title: string;
    readonly visualSystem: OfficePptSceneVisualSystem;
    readonly audience?: string;
    readonly purpose?: OfficeStorySpec['purpose'];
    readonly objective?: string;
    readonly pages: readonly OfficePptScenePage[];
    readonly assets: readonly OfficePptSceneAsset[];
}
/** One deterministic scene-check finding returned to the model. */
export interface OfficePptSceneIssue {
    readonly code: 'duplicate-id' | 'out-of-bounds' | 'overlap' | 'text-overflow' | 'font-size' | 'missing-asset' | 'chart-data' | 'template-reference' | 'template-fidelity';
    readonly severity: 'warning' | 'error';
    readonly page: number;
    readonly elementId?: string;
    readonly message: string;
}
/** Hash-bound result of compiling and inspecting one PPT scene in memory. */
export interface OfficePptSceneCheck {
    readonly status: 'pass' | 'warning' | 'fail';
    readonly sceneHash: string;
    readonly pageCount: number;
    readonly nativeObjectCount: number;
    readonly warningCount: number;
    readonly errorCount: number;
    readonly issues: readonly OfficePptSceneIssue[];
}
/** One editable slide in the DSH-owned presentation model. */
export interface OfficeSlide {
    readonly id: OfficeSlideId;
    readonly role: OfficeSlideRole;
    readonly layout: OfficeLayoutId;
    readonly title: string;
    readonly bullets: readonly string[];
    readonly notes: string;
    readonly sourceRefs: readonly string[];
}
/** One ordered narrative beat retained independently from visual layout. */
export interface OfficeStoryBeat {
    readonly slideId: OfficeSlideId;
    readonly number: number;
    readonly role: OfficeSlideRole;
    readonly job: string;
    readonly claim: string;
}
/** Persisted communication job and narrative arc. */
export interface OfficeStorySpec {
    readonly audience: string;
    readonly purpose: 'inform' | 'persuade' | 'recommend' | 'report';
    readonly objective: string;
    readonly centralTakeaway: string;
    readonly arc: 'context-evidence-action' | 'question-analysis-answer' | 'problem-options-recommendation' | 'current-change-future';
    readonly beats: readonly OfficeStoryBeat[];
}
/** Persisted visual system used by every registered layout. */
export interface OfficeDesignSpec {
    readonly density: 'light' | 'balanced' | 'dense';
    readonly imageStrategy: 'none' | 'supporting' | 'hero';
    readonly chartStrategy: 'none' | 'when-numeric' | 'data-first';
    readonly titleFontFace: string;
    readonly bodyFontFace: string;
    readonly minimumFontSizes: {
        readonly deckTitle: number;
        readonly slideTitle: number;
        readonly callout: number;
        readonly body: number;
    };
    readonly margins: {
        readonly left: number;
        readonly right: number;
        readonly top: number;
        readonly bottom: number;
    };
}
/** Observable mapping from one narrative beat to components and a registered layout. */
export interface OfficeSlidePlan {
    readonly slideId: OfficeSlideId;
    readonly number: number;
    readonly role: OfficeSlideRole;
    readonly layout: OfficeLayoutId;
    readonly layoutSource: 'automatic' | 'requested' | 'legacy' | 'adapted';
    readonly rationale: string;
    readonly components: readonly string[];
    readonly templateReference?: {
        readonly sourceSlideNumber: number;
        readonly sourceTitle: string;
        readonly family: OfficeTemplateLayoutFamily;
        readonly rationale: string;
        readonly contentRelationship?: OfficeTemplatePageRelationship;
    };
}
/** One deterministic page-level QA issue. */
export interface OfficeQaIssue {
    readonly code: 'content-capacity' | 'title-capacity' | 'chart-data' | 'out-of-bounds' | 'overlap' | 'font-size' | 'missing-source' | 'missing-asset' | 'native-object' | 'template-reference' | 'template-fidelity';
    readonly severity: 'warning' | 'error';
    readonly message: string;
}
/** Page-level QA result retained with every immutable revision. */
export interface OfficeSlideQa {
    readonly slideId: OfficeSlideId;
    readonly number: number;
    readonly layout: OfficeLayoutId;
    readonly status: 'pass' | 'warning' | 'fail';
    readonly nativeObjectCount: number;
    readonly issues: readonly OfficeQaIssue[];
}
/** Aggregate deterministic QA evidence for one deck revision. */
export interface OfficeQaReport {
    readonly status: 'not-run' | 'pass' | 'warning' | 'fail';
    readonly checkedAt: string;
    readonly slides: readonly OfficeSlideQa[];
    readonly warningCount: number;
    readonly errorCount: number;
}
/** Evidence about the native PPTX produced for one revision. */
export interface OfficePptOutput {
    readonly fileName: string;
    /** Plugin-root-relative key; callers cannot choose or resolve a Host path. */
    readonly storageKey: string;
    /** Absolute non-hidden folder published directly below the active workspace for user delivery. */
    readonly workspaceDirectoryPath?: string;
    /** Absolute user-facing PPTX path inside workspaceDirectoryPath. */
    readonly workspaceFilePath?: string;
    readonly sha256: string;
    readonly sizeBytes: number;
    readonly nativeObjectCount: number;
    readonly generatedAt: string;
    /** Renderer that produced this immutable revision; absent only on state written before this field existed. */
    readonly renderBackend?: 'native-pptxgenjs' | 'scene-pptxgenjs' | 'dsh-pptd-compatible' | 'dsh-pptd-v2';
}
/** Persisted evidence that the material and scratch phases ran in order. */
export type OfficeWorkflowSpec = {
    readonly route: 'create-from-scratch';
    readonly stages: readonly ['create-from-scratch'];
    /** Uploaded attachments and extracted-template sources used during material analysis. */
    readonly materialRefs: readonly string[];
} | {
    readonly route: 'create-from-material-then-scratch';
    readonly stages: readonly ['create-from-material', 'create-from-scratch'];
    /** Uploaded attachments and extracted-template sources used during material analysis. */
    readonly materialRefs: readonly string[];
};
/** User- or agent-initiated mutation recorded for inspection. */
export interface OfficeActivity {
    readonly id: OfficeActivityId;
    readonly operation: 'create' | 'select-template' | 'select-presentation-mode' | 'deselect-template';
    readonly actor: 'user' | 'agent';
    readonly status: 'completed' | 'failed';
    readonly startedAt: string;
    readonly completedAt: string;
    readonly durationMs: number;
    readonly summary: string;
    readonly error?: string;
}
/** Persisted presentation model plus its current native output. */
export interface OfficeDeck {
    readonly id: OfficeDeckId;
    readonly title: string;
    readonly template: OfficeTemplate;
    readonly slides: readonly OfficeSlide[];
    readonly story: OfficeStorySpec;
    readonly design: OfficeDesignSpec;
    readonly plan: readonly OfficeSlidePlan[];
    readonly workflow: OfficeWorkflowSpec;
    readonly qa: OfficeQaReport;
    readonly revision: number;
    readonly output: OfficePptOutput;
    readonly createdAt: string;
    readonly updatedAt: string;
}
/** Browser-safe projection of the persisted final deck used by the delivery player. */
export interface OfficeDeckPreview {
    readonly id: OfficeDeckId;
    readonly title: string;
    readonly revision: number;
    readonly fileName: string;
    readonly renderBackend: 'native-pptxgenjs' | 'scene-pptxgenjs' | 'dsh-pptd-compatible' | 'dsh-pptd-v2';
    readonly template: OfficeTemplate;
    /** Final output bytes rendered locally in the browser; paths and engine URLs stay Host-owned. */
    readonly finalFile?: {
        readonly mediaType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation';
        readonly byteLength: number;
        readonly contentBase64: string;
    };
    /** Explicit reason that the player is showing its semantic structure fallback. */
    readonly fallbackReason?: 'file-too-large';
    readonly slides: readonly {
        readonly id: OfficeSlideId;
        readonly number: number;
        readonly role: OfficeSlideRole;
        readonly layout: OfficeLayoutId;
        readonly title: string;
        readonly bullets: readonly string[];
    }[];
}
/** Session-local state rendered by the PPT view. */
export interface OfficePptState {
    readonly sessionId: SessionId;
    readonly templates: readonly OfficeTemplate[];
    /** Active composer workflow. It is model context, never visible draft text. */
    readonly presentationMode?: OfficePresentationMode;
    readonly documentMode?: 'word' | 'excel';
    readonly selectedDocumentTemplate?: { readonly id: string; readonly mode: 'word' | 'excel'; readonly revision: string };
    /** Template selected by the resident composer. The model tool uses it when template_id is omitted. */
    readonly selectedTemplateId?: OfficeTemplateId;
    readonly templateMigration?: { readonly reason: 'template-retired' | 'personal-template-deleted'; readonly replacementId?: OfficeTemplateId };
    readonly decks: readonly OfficeDeck[];
    readonly activities: readonly OfficeActivity[];
}
/** Editable outline returned from an uploaded content source. */
export interface OfficeOutlineDraft {
    readonly title: string;
    readonly slides: readonly OfficeDraftSlide[];
    readonly source: {
        readonly fileName: string;
        readonly sha256: string;
        readonly kind: 'pptx' | 'docx' | 'markdown' | 'text';
        /** Number of source sections before the host-side generation ceiling is applied. */
        readonly totalSlideCount: number;
        /** Number of editable sections returned to the composer. */
        readonly extractedSlideCount: number;
        /** Whether additional source sections were intentionally omitted. */
        readonly truncated: boolean;
    };
}
/** One unplanned input slide accepted from extraction, browser RPC, or a model tool. */
export interface OfficeDraftSlide {
    readonly role?: OfficeSlideRole;
    readonly layout?: OfficeLayoutHint;
    readonly title: string;
    readonly bullets: readonly string[];
    readonly notes: string;
    readonly sourceRefs: readonly string[];
    readonly templateReference?: {
        readonly sourceSlideNumber: number;
        readonly rationale: string;
        readonly contentRelationship?: OfficeTemplatePageRelationship;
    };
}
/** Create input shared by browser RPC and the model tool. */
export interface OfficeCreateInput {
    readonly title: string;
    readonly templateId: OfficeTemplateId;
    readonly audience?: string;
    readonly purpose?: OfficeStorySpec['purpose'];
    readonly objective?: string;
    readonly design?: Partial<Pick<OfficeDesignSpec, 'density' | 'imageStrategy' | 'chartStrategy'>>;
    readonly slides: readonly OfficeDraftSlide[];
}
/** Revision-checked focused slide update. */
export interface OfficeUpdateSlideInput {
    readonly deckId: OfficeDeckId;
    readonly slideId: OfficeSlideId;
    readonly expectedRevision: number;
    readonly patch: {
        readonly role?: OfficeSlideRole;
        readonly layout?: OfficeLayoutHint;
        readonly title?: string;
        readonly bullets?: readonly string[];
        readonly notes?: string;
        readonly sourceRefs?: readonly string[];
    };
}
/** Base64 upload request. */
export interface OfficeUploadInput {
    readonly fileName: string;
    readonly contentBase64: string;
}
/** Download response kept on the loopback-only RPC channel. */
export interface OfficeDownload {
    readonly fileName: string;
    readonly mediaType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation';
    readonly contentBase64: string;
}
/** Host location of one generated revision, resolved only from persisted state. */
export interface OfficeOutputLocation {
    readonly fileName: string;
    /** Absolute server-validated PPTX path opened by the local Host. */
    readonly filePath: string;
    readonly directoryPath: string;
}
/** Business failures stay typed inside the generic Connection RPC success value. */
export type OfficeRpcValue<T> = {
    readonly status: 'ok';
    readonly data: T;
} | {
    readonly status: 'error';
    readonly error: {
        readonly code: 'invalid-request' | 'not-found' | 'conflict' | 'unsupported' | 'limit-exceeded' | 'operation-failed';
        readonly message: string;
    };
};
