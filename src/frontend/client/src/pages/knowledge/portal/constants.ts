import type { ComponentProps } from "react";
import { FileStatus, type GroupedKnowledgeSpaces } from "~/api/knowledge";
import LegacyFileIcon from "~/components/ui/icon/File";
import type { PortalFileCategoryOption, SpaceGroupKey } from "./types";

export const EMPTY_GROUPED_SPACES: GroupedKnowledgeSpaces = {
    publicSpaces: [],
    departmentSpaces: [],
    teamSpaces: [],
    personalSpaces: [],
};

export const TREE_PAGE_SIZE = 100;

export const DEFAULT_PORTAL_FILE_CATEGORY_OPTIONS: PortalFileCategoryOption[] = [
    { code: "POL", label: "政策制度" },
    { code: "STD", label: "标准规范" },
    { code: "PRO", label: "流程与程序" },
    { code: "SPC", label: "技术规程与诀窍" },
    { code: "RPT", label: "报告" },
    { code: "CAS", label: "案例" },
    { code: "DGN", label: "设计资产" },
    { code: "PAT", label: "专利与知识产权" },
    { code: "TRN", label: "培训资源" },
];

const KNOWLEDGE_PORTAL_ASSET_BASE = "/assets/knowledge-portal";

export const PORTAL_SIDEBAR_TITLE_ICON_SRC = `${KNOWLEDGE_PORTAL_ASSET_BASE}/sidebar-title.png`;

export const CREATE_KNOWLEDGE_SPACE_ICON_SRC = `${KNOWLEDGE_PORTAL_ASSET_BASE}/create-knowledge-space.png`;

export const KNOWLEDGE_SPACE_ICON_SRC = {
    default: `${KNOWLEDGE_PORTAL_ASSET_BASE}/knowledge-space.png`,
    active: `${KNOWLEDGE_PORTAL_ASSET_BASE}/knowledge-space-active.png`,
};

export const SIDEBAR_TOGGLE_ICON_SRC = {
    collapse: `${KNOWLEDGE_PORTAL_ASSET_BASE}/sidebar-collapse.png`,
    expand: `${KNOWLEDGE_PORTAL_ASSET_BASE}/sidebar-expand.png`,
};

export const FOLDER_ICON_SRC = {
    collapsed: `${KNOWLEDGE_PORTAL_ASSET_BASE}/folder-collapsed.png`,
    expanded: `${KNOWLEDGE_PORTAL_ASSET_BASE}/folder-expanded.png`,
};

export const GROUP_ICON_SRC: Record<SpaceGroupKey, { collapsed: string; expanded: string }> = {
    public: {
        collapsed: `${KNOWLEDGE_PORTAL_ASSET_BASE}/group-public-collapsed.png`,
        expanded: `${KNOWLEDGE_PORTAL_ASSET_BASE}/group-public-expanded.png`,
    },
    department: {
        collapsed: `${KNOWLEDGE_PORTAL_ASSET_BASE}/group-department-collapsed.png`,
        expanded: `${KNOWLEDGE_PORTAL_ASSET_BASE}/group-department-expanded.png`,
    },
    team: {
        collapsed: `${KNOWLEDGE_PORTAL_ASSET_BASE}/group-team-collapsed.png`,
        expanded: `${KNOWLEDGE_PORTAL_ASSET_BASE}/group-team-expanded.png`,
    },
    personal: {
        collapsed: `${KNOWLEDGE_PORTAL_ASSET_BASE}/group-personal-collapsed.png`,
        expanded: `${KNOWLEDGE_PORTAL_ASSET_BASE}/group-personal-expanded.png`,
    },
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
