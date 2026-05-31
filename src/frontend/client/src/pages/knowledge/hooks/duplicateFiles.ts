import {
    FileStatus,
    type KnowledgeFile,
} from "~/api/knowledge";

/** 从 addFiles 返回结果中识别出的重复文件项 */
export interface DuplicateFileEntry {
    fileId: string;
    fileName: string;
    oldFileLevelPath: string;
    /** 覆盖接口需要透传 addFiles 返回的原始对象 */
    rawObj: any;
}

export function extractDuplicateFileEntries(registeredFiles: KnowledgeFile[]): DuplicateFileEntry[] {
    // 后端用 old_file_level_path 标记重复文件；根目录重复时该字段可能是空字符串。
    // 真实解析失败不会带这个字段，所以这里用类型判断保留根目录重复项。
    return registeredFiles
        .filter((file) => (
            file.status === FileStatus.FAILED &&
            typeof file.oldFileLevelPath === "string" &&
            Boolean((file as any)._raw)
        ))
        .map((file) => ({
            fileId: file.id,
            fileName: file.name,
            oldFileLevelPath: file.oldFileLevelPath || "",
            rawObj: (file as any)._raw,
        }));
}
