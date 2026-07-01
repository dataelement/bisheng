import type {
    KnowledgeFile,
    KnowledgeFilePreview,
    KnowledgeSpace,
    SimilarCandidateEntry,
    SpaceLevel,
} from "~/api/knowledge";

export type SpaceGroupKey = "public" | "department" | "team" | "personal";
export type PanelKey = "properties" | "time" | "source" | "usage" | "permission" | "share";
export type PortalToolRailKey = "toggle" | "properties" | "time" | "source" | "usage" | "permission" | "ai";

export interface SpaceGroup {
    key: SpaceGroupKey;
    title: string;
    level: SpaceLevel;
    iconSrc: {
        collapsed: string;
        expanded: string;
    };
    spaces: KnowledgeSpace[];
    loading?: boolean;
}

export interface PreviewState {
    loading: boolean;
    fileUrl: string;
    fileType: string;
    error: string;
    previewData?: KnowledgeFilePreview | null;
}

export interface PortalFileTreeNode {
    file: KnowledgeFile;
    children: PortalFileTreeNode[];
    expanded: boolean;
    loaded: boolean;
    loading: boolean;
    page: number;
    total: number;
}

export type PortalUploadStep = "select" | "review";

export interface PortalFileCategoryOption {
    code: string;
    label: string;
}

export interface PortalUploadFileItem {
    id: string;
    file: File;
    source: "file" | "folder";
}

export interface PortalUploadFolderNode {
    id: string;
    name: string;
    children: PortalUploadFolderNode[];
    expanded: boolean;
    loaded: boolean;
    loading: boolean;
}

export type PortalUploadFolderSelection =
    | { mode: "ai" }
    | { mode: "manual"; folderId: string | null; folderName: string };

export interface PortalUploadReviewRow {
    file: KnowledgeFile;
    selected: boolean;
    recommendedFolderId: string | null;
    recommendedFolderName: string;
    storageFolderId: string | null;
    storageFolderName: string;
    candidates: SimilarCandidateEntry[];
    candidatesLoading: boolean;
    candidateError: boolean;
    selectedTargetDocumentId: number | null;
}
