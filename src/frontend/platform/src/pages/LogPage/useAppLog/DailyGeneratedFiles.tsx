import type { ReactNode } from "react";
import { FileIcon, type FileType } from "@/components/bs-icons/file";
import { getAuditChatFileUrlApi } from "@/controllers/API/log";
import { handleUiRequest } from "@/controllers/request";

/** `source` the backend stamps on files the code interpreter attached to an answer. */
const GENERATED_FILE_SOURCE = "code_interpreter";

export interface GeneratedFile {
    file_id: string;
    file_name: string;
    path?: string;
    source?: string;
}

/** User uploads are outside what an auditor may download; only generated files are shown. */
export function pickGeneratedFiles(files: unknown): GeneratedFile[] {
    if (!Array.isArray(files)) return [];
    return files.filter(
        (file): file is GeneratedFile => !!file && file.source === GENERATED_FILE_SOURCE && !!file.file_id,
    );
}

function normalizeHref(href: string): string {
    let decoded = href;
    try {
        decoded = decodeURIComponent(href);
    } catch {
        // A stray `%` in a model-written link; match it as written.
    }
    return decoded.replace(/\\/g, "/").replace(/^\.\//, "").replace(/^\/+/, "");
}

/** A relative link into the code interpreter's working directory, which is no route of this app. */
export function isWorkspaceRelativeHref(href: string): boolean {
    return /^(output|scratch)\//.test(normalizeHref(href));
}

/** The generated file an answer's link names, matched on its path in the working directory. */
export function matchGeneratedFile(files: GeneratedFile[], href: string): GeneratedFile | undefined {
    if (!href || !files.length || /^[a-z][a-z0-9+.-]*:/i.test(href)) return undefined;
    const target = normalizeHref(href);
    return files.find((file) => file.path && normalizeHref(file.path) === target);
}

async function downloadGeneratedFile(chatId: string, file: GeneratedFile) {
    const { url } = await getAuditChatFileUrlApi(chatId, file.file_id);
    const link = document.createElement("a");
    link.href = url;
    link.download = file.file_name;
    link.click();
}

const openGeneratedFile = handleUiRequest(downloadGeneratedFile);

function fileTypeOf(fileName: string): FileType {
    return (fileName.split(".").pop() || "txt").toLowerCase() as FileType;
}

/** Download cards for the files the code interpreter attached to an answer. */
export function GeneratedFileCards({ chatId, files }: { chatId: string; files: GeneratedFile[] }) {
    if (!files.length) return null;
    return (
        <div className="not-prose mt-2 flex flex-wrap gap-2">
            {files.map((file) => (
                <button
                    key={file.file_id}
                    type="button"
                    title={file.file_name}
                    className="flex max-w-[280px] items-center gap-2 rounded-md border border-border-base bg-fill-1 px-3 py-2 text-left hover:bg-fill-2"
                    onClick={() => openGeneratedFile(chatId, file)}
                >
                    <FileIcon type={fileTypeOf(file.file_name)} className="size-6 shrink-0" />
                    <span className="truncate text-body-sm text-text-1">{file.file_name}</span>
                </button>
            ))}
        </div>
    );
}

/**
 * Link renderer for an audited daily-chat answer: a link naming a generated
 * file downloads it; a working-directory link naming nothing becomes plain
 * text; any other link is left to the default renderer (undefined).
 */
export function renderGeneratedFileLink(
    chatId: string,
    files: GeneratedFile[],
    href: string | undefined,
    children: ReactNode,
): ReactNode | undefined {
    if (!href) return undefined;
    const matched = matchGeneratedFile(files, href);
    if (matched) {
        return (
            <button
                type="button"
                className="text-primary underline"
                onClick={() => openGeneratedFile(chatId, matched)}
            >
                {children}
            </button>
        );
    }
    if (isWorkspaceRelativeHref(href)) return <span>{children}</span>;
    return undefined;
}
