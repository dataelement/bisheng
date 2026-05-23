import type {
    KnowledgeFile,
    KnowledgeSpace,
    SimilarCandidateEntry,
    SpaceLevel,
} from "~/api/knowledge";

export type SpaceGroupKey = "public" | "department" | "team" | "personal";
export type PanelKey = "properties" | "time" | "source" | "usage" | "share";
export type PortalToolRailKey = "toggle" | "properties" | "time" | "source" | "usage" | "permission";

export interface SpaceGroup {
    key: SpaceGroupKey;
    title: string;
    level: SpaceLevel;
    iconSrc: string;
    spaces: KnowledgeSpace[];
}

export interface PreviewState {
    loading: boolean;
    fileUrl: string;
    fileType: string;
    error: string;
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
