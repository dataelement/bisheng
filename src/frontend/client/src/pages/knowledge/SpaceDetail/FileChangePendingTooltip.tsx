import { useQuery } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";

import {
    FileType,
    getFileChangeDetailApi,
    type FileChangeDetail,
    type KnowledgeFile,
} from "~/api/knowledge";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { useLocalize } from "~/hooks";
import { formatTime } from "../knowledgeUtils";

/**
 * Hover card for the pending-approval pill: what was requested, by whom, on
 * what (Figma 13198:78120).
 *
 * A pending upload carries everything in the row projection, so its summary is
 * built locally. rename / move / delete only expose action + ids on the row —
 * old/new names and paths live in the change-request detail, so that one is
 * fetched the first time the tooltip opens (shared query key with the detail
 * dialog, so opening one warms the other).
 */
interface FileChangePendingTooltipProps {
    file: KnowledgeFile;
    /** List rows place the tooltip beside the pill, cards above it. */
    side: "left" | "top";
    children: ReactElement;
}

export function FileChangePendingTooltip({ file, side, children }: FileChangePendingTooltipProps) {
    const localize = useLocalize();
    const [open, setOpen] = useState(false);
    const approval = file.fileChangeApproval;
    const pendingUpload = file.pendingUploadApproval;

    const { data: detail } = useQuery({
        queryKey: ["knowledge-file-change-detail", file.spaceId, approval?.requestId],
        queryFn: () => getFileChangeDetailApi(file.spaceId, approval!.requestId),
        enabled: open && Boolean(approval?.requestId) && Boolean(file.spaceId),
        staleTime: 30_000,
    });

    const segments: string[] = [];
    if (pendingUpload) {
        segments.push(
            localize("com_knowledge.file_change_tip_action", {
                0: localize("com_knowledge.file_change_tip_action_upload"),
            }),
        );
        if (pendingUpload.applicantUserName) {
            segments.push(
                localize("com_knowledge.file_change_tip_applicant", { 0: pendingUpload.applicantUserName }),
            );
        }
        if (pendingUpload.createTime) {
            segments.push(
                localize("com_knowledge.file_change_tip_time", { 0: formatTime(pendingUpload.createTime) }),
            );
        }
    } else if (approval) {
        segments.push(...buildApprovalSegments({ file, action: approval.action, detail, localize }));
    }

    if (!segments.length) return children;

    return (
        <Tooltip onOpenChange={setOpen}>
            <TooltipTrigger asChild>{children}</TooltipTrigger>
            <TooltipContent side={side} className="z-[999] flex max-w-md flex-col gap-0.5">
                {segments.map((line, index) => <span key={index}>{line}</span>)}
            </TooltipContent>
        </Tooltip>
    );
}

function buildApprovalSegments({
    file,
    action,
    detail,
    localize,
}: {
    file: KnowledgeFile;
    action: "rename" | "move" | "delete";
    detail?: FileChangeDetail;
    localize: ReturnType<typeof useLocalize>;
}): string[] {
    const isFolder = file.type === FileType.FOLDER;
    const applicant = detail?.applicantUserName;
    const applicantSegment = applicant
        ? [localize("com_knowledge.file_change_tip_applicant", { 0: applicant })]
        : [];

    if (action === "delete") {
        const actionSegment = localize("com_knowledge.file_change_tip_action", {
            0: localize(
                isFolder
                    ? "com_knowledge.file_change_tip_action_delete_folder"
                    : "com_knowledge.file_change_tip_action_delete_file",
            ),
        });
        const name = detail?.resourceName || file.name;
        if (isFolder) {
            return [actionSegment, describeFolderScope(file, name, localize)];
        }
        return [
            actionSegment,
            ...applicantSegment,
            localize("com_knowledge.file_change_tip_delete_target", { 0: name }),
        ];
    }

    if (action === "rename") {
        const actionSegment = localize("com_knowledge.file_change_tip_action", {
            0: localize("com_knowledge.file_change_tip_action_rename"),
        });
        const oldName = detail?.actionDetail.oldName;
        const newName = detail?.actionDetail.newName;
        if (!oldName || !newName) return [actionSegment];
        return [
            actionSegment,
            localize("com_knowledge.file_change_tip_rename_detail", { 0: oldName, 1: newName }),
        ];
    }

    const actionSegment = localize("com_knowledge.file_change_tip_action", {
        0: localize("com_knowledge.file_change_tip_action_move"),
    });
    const sourcePath = detail?.actionDetail.sourcePath;
    const targetPath = detail?.actionDetail.targetPath;
    if (!sourcePath || !targetPath) return [actionSegment];
    return [
        actionSegment,
        localize("com_knowledge.file_change_tip_move_detail", { 0: sourcePath, 1: targetPath }),
    ];
}

/**
 * Folder rows only report success / processing child counts (plus a
 * has-failures flag) — no total. Naming an exact figure would undercount
 * failed children, so the count is stated only when nothing failed, and the
 * wording falls back to "all files it contains" otherwise.
 */
function describeFolderScope(
    file: KnowledgeFile,
    name: string,
    localize: ReturnType<typeof useLocalize>,
): string {
    const counted = file.successFileNum != null || file.processingFileNum != null;
    if (!counted || file.hasFailedFiles !== false) {
        return localize("com_knowledge.file_change_tip_delete_folder_scope_all", { 0: name });
    }
    const total = (file.successFileNum ?? 0) + (file.processingFileNum ?? 0);
    return localize("com_knowledge.file_change_tip_delete_folder_scope", { 0: name, 1: total });
}
