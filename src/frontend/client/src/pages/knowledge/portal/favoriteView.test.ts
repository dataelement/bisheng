import type { PortalFavoriteFile } from "~/api/knowledge";
import { isFavoriteSpace, toFavoriteRow } from "./favoriteView";

function makeFav(overrides: Partial<PortalFavoriteFile> = {}): PortalFavoriteFile {
    return {
        favoriteFileId: "f1",
        sourceSpaceId: "s1",
        sourceFileId: "file1",
        title: "标题",
        fileName: "report.pdf",
        status: "valid",
        updatedAt: "2026-01-01",
        ...overrides,
    };
}

describe("isFavoriteSpace", () => {
    it("returns true when isFavorite is true", () => {
        expect(isFavoriteSpace({ isFavorite: true })).toBe(true);
    });

    it("returns false when isFavorite is false", () => {
        expect(isFavoriteSpace({ isFavorite: false })).toBe(false);
    });

    it("returns false for null/undefined", () => {
        expect(isFavoriteSpace(null)).toBe(false);
        expect(isFavoriteSpace(undefined)).toBe(false);
    });
});

describe("toFavoriteRow", () => {
    it("maps an invalid favorite to a non-openable row", () => {
        const row = toFavoriteRow(makeFav({ status: "invalid" }));
        expect(row.invalid).toBe(true);
        expect(row.openable).toBe(false);
    });

    it("maps a valid favorite to an openable row", () => {
        const row = toFavoriteRow(makeFav({ status: "valid" }));
        expect(row.invalid).toBe(false);
        expect(row.openable).toBe(true);
    });

    it("carries identity fields through to the row", () => {
        const row = toFavoriteRow(makeFav({ favoriteFileId: "fav9", sourceSpaceId: "12", sourceFileId: "34" }));
        expect(row.key).toBe("fav9");
        expect(row.sourceSpaceId).toBe("12");
        expect(row.sourceFileId).toBe("34");
    });

    it("falls back from title to fileName to 未命名", () => {
        expect(toFavoriteRow(makeFav({ title: "T", fileName: "a.pdf" })).title).toBe("T");
        expect(toFavoriteRow(makeFav({ title: "", fileName: "a.pdf" })).title).toBe("a.pdf");
        expect(toFavoriteRow(makeFav({ title: "", fileName: "" })).title).toBe("未命名");
    });
});
