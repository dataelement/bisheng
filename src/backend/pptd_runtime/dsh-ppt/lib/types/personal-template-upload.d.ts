/** Per-request transport budget; the complete source file has no product size cap. */
export declare const PERSONAL_TEMPLATE_CHUNK_BYTES: number;
export declare function personalTemplateFileName(value: unknown): string;
export declare function decodeTemplateBase64(encoded: unknown): Buffer;
export interface PersonalTemplateUploadFiles {
  readonly root: string;
  directory(...parts: string[]): Promise<string>;
  checkedFile(directory: string, file: string): Promise<string>;
}
export interface PersonalTemplateUploadInput { readonly fileName: string; readonly size: number; }
export interface PersonalTemplateUploadChunk { readonly uploadId: string; readonly offset: number; readonly base64: string; }
/** Operations execute under the owning library policy/audit lock. */
export declare class PersonalTemplateUploads {
  constructor(files: PersonalTemplateUploadFiles);
  private record;
  start(session: string, input: PersonalTemplateUploadInput): Promise<{uploadId: string; chunkBytes: number}>;
  append(session: string, input: PersonalTemplateUploadChunk): Promise<{received: number; size: number}>;
  read(session: string, uploadId: string): Promise<{bytes: Buffer; fileName: string; directory: string}>;
  cancel(session: string, uploadId: string): Promise<{uploadId: string}>;
}
