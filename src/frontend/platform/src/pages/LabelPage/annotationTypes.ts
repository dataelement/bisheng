export interface AnnotationQa { q: string; a: string }
export interface AnnotationFormHandle { open: (id: string, qa: AnnotationQa) => void }
export interface AnnotationFormProps { onMarked?: () => void }
