/** Atomic, non-overwriting publication primitives shared by PPTD CLI and model tools. */
import type { PptdProjectSource } from './pptd.ts';
/** Atomically publish one file, preserving an existing target unless replacement was explicitly requested. */
export declare function publishPptdFile(target: string, bytes: Uint8Array, replace: boolean): Promise<void>;
/** Atomically publish one directory, preserving an existing target unless replacement was explicitly requested. */
export declare function publishPptdDirectory(target: string, replace: boolean, writer: (stagingDirectory: string) => Promise<void>): Promise<void>;
/** Materialize a confined, self-contained PPTD source plane inside an empty staging directory. */
export declare function writePptdProjectSource(directory: string, source: PptdProjectSource): Promise<void>;