export interface PersonalTemplateImportJob {
  root: string;
  sessionId: string;
  uploadId: string;
  draftId: string;
  maxSlides: number;
}
export interface PersonalTemplateImportProgress {
  total: number;
  page?: {page: number; preview: string};
}
/** Caller holds the host library policy and audit lock. Source assets stay on disk. */
export declare function runPersonalTemplateImport(
  job: PersonalTemplateImportJob,
  onProgress?: (progress: PersonalTemplateImportProgress) => void,
  options?: {timeoutMs?: number; maxHeapMiB?: number; signal?: AbortSignal}
): Promise<{draftId?: string; duplicate?: boolean; template: Record<string, unknown>; preview?: string}>;
