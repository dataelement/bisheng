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

interface DuplicateRemark {
    newName?: string;
}

function parseDuplicateRemark(rawObj: any): DuplicateRemark | null {
    if (rawObj?.repeat === true) {
        return {
            newName: typeof rawObj.file_name === "string" ? rawObj.file_name : undefined,
        };
    }

    if (typeof rawObj?.remark !== "string" || !rawObj.remark.trim()) {
        return null;
    }

    try {
        const remark = JSON.parse(rawObj.remark);
        const hasDuplicateNames =
            typeof remark?.new_name === "string" ||
            typeof remark?.old_name === "string";
        if (!hasDuplicateNames) {
            return null;
        }
        return {
            newName: typeof remark.new_name === "string" ? remark.new_name : undefined,
        };
    } catch {
        return null;
    }
}

export function extractDuplicateFileEntries(registeredFiles: KnowledgeFile[]): DuplicateFileEntry[] {
    // Prefer old_file_level_path, but keep compatibility with responses that only
    // expose the duplicate marker in remark. Root-level duplicates can use "".
    return registeredFiles
        .map((file) => {
            const rawObj = (file as any)._raw;
            if (file.status !== FileStatus.FAILED || !rawObj) {
                return null;
            }

            const duplicateRemark = parseDuplicateRemark(rawObj);
            const rawOldFileLevelPath = rawObj.old_file_level_path;
            const hasDuplicatePath =
                typeof file.oldFileLevelPath === "string" ||
                typeof rawOldFileLevelPath === "string";
            if (!hasDuplicatePath && !duplicateRemark) {
                return null;
            }

            return {
                fileId: file.id,
                fileName: duplicateRemark?.newName || file.name,
                oldFileLevelPath:
                    file.oldFileLevelPath ??
                    (typeof rawOldFileLevelPath === "string" ? rawOldFileLevelPath : ""),
                rawObj,
            };
        })
        .filter((entry): entry is DuplicateFileEntry => entry !== null);
}
