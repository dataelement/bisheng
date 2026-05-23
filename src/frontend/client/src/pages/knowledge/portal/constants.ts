import type { ComponentProps } from "react";
import { FileStatus, type GroupedKnowledgeSpaces } from "~/api/knowledge";
import LegacyFileIcon from "~/components/ui/icon/File";
import type { SpaceGroupKey } from "./types";

export const EMPTY_GROUPED_SPACES: GroupedKnowledgeSpaces = {
    publicSpaces: [],
    departmentSpaces: [],
    teamSpaces: [],
    personalSpaces: [],
};

export const TREE_PAGE_SIZE = 100;

export const GROUP_ICON_SRC: Record<SpaceGroupKey, string> = {
    public: "/assets/knowledge-portal/space-public.png",
    department: "/assets/knowledge-portal/space-department.png",
    team: "/assets/knowledge-portal/space-team.png",
    personal: "/assets/knowledge-portal/space-personal.png",
};

export const STATUS_FILTER_OPTIONS: Array<{ status: FileStatus; label: string }> = [
    { status: FileStatus.UPLOADING, label: "上传中" },
    { status: FileStatus.WAITING, label: "排队中" },
    { status: FileStatus.PROCESSING, label: "解析中" },
    { status: FileStatus.REBUILDING, label: "重建中" },
    { status: FileStatus.SUCCESS, label: "成功" },
    { status: FileStatus.FAILED, label: "失败" },
    { status: FileStatus.VIOLATION, label: "违规" },
    { status: FileStatus.TIMEOUT, label: "超时" },
];

export type LegacyFileIconType = ComponentProps<typeof LegacyFileIcon>["type"];

export const LEGACY_FILE_ICON_TYPE_BY_EXTENSION: Record<string, LegacyFileIconType | "xlsx"> = {
    md: "md",
    txt: "txt",
    html: "html",
    csv: "csv",
    xls: "csv",
    xlsx: "xlsx",
    pdf: "pdf",
    doc: "doc",
    docx: "docx",
};
