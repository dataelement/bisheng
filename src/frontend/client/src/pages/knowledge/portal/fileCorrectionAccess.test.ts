import { SpaceLevel } from "~/api/knowledge";
import { canOpenFileCorrection, canSubmitFileCorrection } from "./fileCorrectionAccess";

describe("canSubmitFileCorrection", () => {
    const space = { spaceLevel: SpaceLevel.DEPARTMENT, isFavorite: false };

    it("shows the action for another reader on an eligible library", () => {
        expect(canSubmitFileCorrection({
            space,
            file: { uploaderUserId: 8 },
            currentUserId: 3,
        })).toBe(true);
    });

    it("hides the action when the reader is the uploader", () => {
        expect(canSubmitFileCorrection({
            space,
            file: { uploaderUserId: 3 },
            currentUserId: "3",
        })).toBe(false);
    });

    it("lets the uploader open the history without submitting", () => {
        expect(canOpenFileCorrection({
            space,
            file: { uploaderUserId: 3 },
        })).toBe(true);
        expect(canSubmitFileCorrection({
            space,
            file: { uploaderUserId: 3 },
            currentUserId: "3",
        })).toBe(false);
    });

    it("hides personal and favorite libraries", () => {
        expect(canSubmitFileCorrection({
            space: { spaceLevel: SpaceLevel.PERSONAL, isFavorite: false },
            file: { uploaderUserId: 8 },
            currentUserId: 3,
        })).toBe(false);
        expect(canSubmitFileCorrection({
            space: { spaceLevel: SpaceLevel.PUBLIC, isFavorite: true },
            file: { uploaderUserId: 8 },
            currentUserId: 3,
        })).toBe(false);
    });
});
