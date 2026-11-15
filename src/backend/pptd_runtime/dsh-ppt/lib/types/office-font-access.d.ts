/** Host-selected check of the optional macOS Office font-cache directory. */
export declare function prepareOfficeFontAccess(options?: {
  platform?: NodeJS.Platform;
  home?: string;
  openDirectory?: (directory: string) => Promise<{read(): Promise<unknown>; close(): Promise<void>}>;
}): Promise<{status: 'not-required' | 'ready' | 'absent' | 'restricted'}>;
