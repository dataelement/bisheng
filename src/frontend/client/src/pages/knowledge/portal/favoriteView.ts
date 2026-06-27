import type { PortalFavoriteFile } from "~/api/knowledge";

/** 判断一个知识空间是否为"我的收藏"虚拟库。 */
export function isFavoriteSpace(space: { isFavorite?: boolean } | null | undefined): boolean {
    return Boolean(space?.isFavorite);
}

/** 收藏列表行的展示/判定视图模型（纯数据，便于单测）。 */
export interface FavoriteRowVM {
    /** React key — 收藏记录唯一 id */
    key: string;
    /** 展示标题（title → fileName → "未命名"） */
    title: string;
    /** 源文件是否已失效（不可打开） */
    invalid: boolean;
    /** 源知识库 id */
    sourceSpaceId: string;
    /** 源文件 id */
    sourceFileId: string;
    /** 是否可打开（= !invalid） */
    openable: boolean;
}

/** 将后端收藏文件项映射为只读列表行视图模型。 */
export function toFavoriteRow(fav: PortalFavoriteFile): FavoriteRowVM {
    const invalid = fav.status === "invalid";
    return {
        key: fav.favoriteFileId,
        title: fav.title || fav.fileName || "未命名",
        invalid,
        sourceSpaceId: fav.sourceSpaceId,
        sourceFileId: fav.sourceFileId,
        openable: !invalid,
    };
}
