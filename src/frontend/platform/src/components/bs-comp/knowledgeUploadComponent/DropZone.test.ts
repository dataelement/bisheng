import { describe, expect, it } from "vitest";

import { getKnowledgeUploadAccept, getKnowledgeUploadFormats } from "./DropZone";

const MEDIA_FORMATS = ['.MP3', '.WAV', '.M4A', '.AAC', '.FLAC', '.OGG', '.MP4', '.MOV', '.AVI', '.MKV', '.WEBM'];

describe("knowledge upload capabilities", () => {
    it.each([false, true])("removes media formats and MIME groups when ETL4LM is %s", (enableEtl4lm) => {
        const formats = getKnowledgeUploadFormats(enableEtl4lm, false);
        const accept = getKnowledgeUploadAccept(formats, false);

        for (const mediaFormat of MEDIA_FORMATS) {
            expect(formats).not.toContain(mediaFormat);
        }
        expect(accept).not.toHaveProperty("audio/*");
        expect(accept).not.toHaveProperty("video/*");
        expect(formats).toContain(".PDF");
    });

    it.each([false, true])("restores media formats and MIME groups when ETL4LM is %s", (enableEtl4lm) => {
        const formats = getKnowledgeUploadFormats(enableEtl4lm, true);
        const accept = getKnowledgeUploadAccept(formats, true);

        for (const mediaFormat of MEDIA_FORMATS) {
            expect(formats).toContain(mediaFormat);
        }
        expect(accept).toHaveProperty("audio/*");
        expect(accept).toHaveProperty("video/*");
        expect(formats).toContain(".PDF");
    });
});
