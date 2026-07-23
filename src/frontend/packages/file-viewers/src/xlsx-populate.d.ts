// xlsx-populate ships no TypeScript types. We only touch its zip internals for
// image extraction, so declare the minimal surface actually used.
declare module 'xlsx-populate/browser/xlsx-populate' {
  export interface ZipEntry {
    dir: boolean;
    async(type: 'base64' | 'text'): Promise<string>;
  }
  export interface Zip {
    files: Record<string, ZipEntry>;
    file(path: string): ZipEntry | null;
    forEach(cb: (relativePath: string, entry: ZipEntry) => void): void;
  }
  export interface Workbook {
    _zip: Zip;
  }
  const XlsxPopulate: {
    fromDataAsync(data: ArrayBuffer): Promise<Workbook>;
  };
  export default XlsxPopulate;
}
