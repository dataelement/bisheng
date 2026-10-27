import type { QaOperation } from '@bisheng/chat/core';
export interface AnnotationQa { q: string; a: string }
export interface AnnotationFormHandle {
    open: (id: string, qa: AnnotationQa, operation?: Readonly<QaOperation>) => void;
    close: () => void;
}
export interface AnnotationFormProps { onMarked?: (operation?: Readonly<QaOperation>) => void | Promise<void> }
