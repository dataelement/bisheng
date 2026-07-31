export interface AppChatFileLike {
    name?: string;
    file_name?: string;
    filename?: string;
    path?: string;
    file_path?: string;
    filepath?: string;
    file_url?: string;
    url?: string;
    cover_filepath?: string;
    mediaDurationSec?: number;
    parsingState?: 'parsing' | 'done';
}

export function normalizeAppChatFile(file: AppChatFileLike): { name: string; path: string } {
    const name = file.file_name || file.name || file.filename || 'File';
    const path =
        file.file_url ||
        file.filepath ||
        file.file_path ||
        file.path ||
        file.url ||
        '';
    return { name, path };
}
