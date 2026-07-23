import { FileType } from "~/api/knowledge";
import {
    MEDIA_FILE_EXTENSIONS,
    getAllowedExtensions,
    getAllowedMimeTypes,
    getFileInputAccept,
    getFileTypeFromName,
} from "./knowledgeUtils";

describe("knowledge upload capabilities", () => {
    test.each([false, true])("excludes media from every upload path when ETL4LM is %s", (enableEtl4lm) => {
        const extensions = getAllowedExtensions(enableEtl4lm, false);
        const mimeTypes = getAllowedMimeTypes(enableEtl4lm, false);
        const inputAccept = getFileInputAccept(enableEtl4lm, false).split(",");

        for (const extension of MEDIA_FILE_EXTENSIONS) {
            expect(extensions).not.toContain(extension);
            expect(inputAccept).not.toContain(`.${extension}`);
        }
        expect(mimeTypes.some((mimeType) => mimeType.startsWith("audio/"))).toBe(false);
        expect(mimeTypes.some((mimeType) => mimeType.startsWith("video/"))).toBe(false);
        expect(extensions).toContain("pdf");
    });

    test.each([false, true])("restores media in every upload path when ETL4LM is %s", (enableEtl4lm) => {
        const extensions = getAllowedExtensions(enableEtl4lm, true);
        const mimeTypes = getAllowedMimeTypes(enableEtl4lm, true);
        const inputAccept = getFileInputAccept(enableEtl4lm, true).split(",");

        for (const extension of MEDIA_FILE_EXTENSIONS) {
            expect(extensions).toContain(extension);
            expect(inputAccept).toContain(`.${extension}`);
        }
        expect(mimeTypes.some((mimeType) => mimeType.startsWith("audio/"))).toBe(true);
        expect(mimeTypes.some((mimeType) => mimeType.startsWith("video/"))).toBe(true);
        expect(extensions).toContain("pdf");
    });

    test("keeps historical media type recognition available", () => {
        expect(getFileTypeFromName("recording.mp3")).toBe(FileType.AUDIO);
        expect(getFileTypeFromName("meeting.mp4")).toBe(FileType.VIDEO);
    });
});
