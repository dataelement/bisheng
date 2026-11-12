/** Office PPT composer-mode dictionaries. */
/** Locale namespace. */
export declare const NS = "dsh-ppt";
/** Visible copy keys. */
export type OfficePptKey = 'mode.label' | 'mode.region' | 'composer.selectedTemplate' | 'composer.removeTemplate' | 'templates.title' | 'templates.categories' | 'templates.empty' | 'templates.loadTimeout' | 'templates.retry' | 'templates.category.all' | 'templates.category.custom' | 'templates.category.business' | 'templates.category.strategy' | 'templates.category.consulting' | 'templates.category.finance' | 'templates.category.work' | 'templates.category.promotion' | 'templates.category.academic' | 'templates.category.data' | 'templates.category.editorial' | 'templates.category.briefing' | 'status.loading' | 'tool.structure' | 'tool.structure.open' | 'tool.pages' | 'tool.inspect' | 'tool.plan' | 'tool.plan.story' | 'tool.plan.layouts' | 'tool.plan.qa' | 'tool.preview' | 'tool.preview.loading' | 'tool.preview.failed' | 'tool.preview.previous' | 'tool.preview.next' | 'tool.preview.slide' | 'tool.preview.retry' | 'tool.preview.revision' | 'tool.preview.rendering' | 'tool.preview.structure' | 'tool.preview.structureOnly' | 'tool.preview.structureFailed' | 'tool.preview.structureLarge' | 'tool.artifact' | 'tool.artifact.saved' | 'tool.artifact.fallback' | 'tool.download' | 'tool.openFile' | 'tool.openFolder' | 'tool.downloading' | 'tool.openingFile' | 'tool.openingFolder' | 'tool.fileActionFailed' | 'tool.create.running' | 'tool.create.done' | 'tool.create.failed' | 'tool.update.running' | 'tool.update.done' | 'tool.update.failed' | 'tool.update.content';
declare module '@deepseek-ai/dsh-client-ui-slots' {
    interface LocaleNamespaceMap {
        /** PPT mode and template chooser shown on the New Session page. */
        'dsh-ppt': OfficePptKey;
    }
}
/** Simplified Chinese dictionary. */
export declare const zh: Record<OfficePptKey, string>;
/** English dictionary. */
export declare const en: Record<OfficePptKey, string>;