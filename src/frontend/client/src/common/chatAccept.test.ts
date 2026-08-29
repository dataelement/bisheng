import { buildChatAccept, isFileNameAccepted } from "./chatAccept";

const DAILY = { enableMedia: false, enableEtl4lm: false, includeOfd: true };

describe("buildChatAccept", () => {
    it("keeps daily chat on the document-only list", () => {
        // Daily chat extracts attachment text into the prompt via the document
        // parser, so an unparseable type fails the whole turn rather than being
        // ignored. This string is a regression pin, not a preference.
        expect(buildChatAccept(DAILY)).toBe(
            ".pdf,.txt,.docx,.doc,.ppt,.pptx,.md,.html,.xls,.xlsx,.wps,.dps,.et,.ofd",
        );
    });

    it("is unchanged by taskMode:false", () => {
        expect(buildChatAccept({ ...DAILY, taskMode: false })).toBe(buildChatAccept(DAILY));
    });

    it("adds data/config/source files in task mode", () => {
        const accept = buildChatAccept({ ...DAILY, taskMode: true });
        for (const ext of [".csv", ".py", ".json", ".yaml", ".sql", ".sh", ".ts", ".tsv"]) {
            expect(accept.split(",")).toContain(ext);
        }
        // The document list survives alongside them.
        expect(accept.split(",")).toContain(".pdf");
    });

    it("still honours the image and media switches in task mode", () => {
        const accept = buildChatAccept({
            enableMedia: true,
            enableEtl4lm: true,
            includeOfd: true,
            taskMode: true,
        });
        expect(accept.split(",")).toEqual(expect.arrayContaining([".png", ".mp3", ".mp4", ".py"]));
    });

    it("allows backend-supported image formats for a vision model", () => {
        const accept = buildChatAccept({ ...DAILY, enableVision: true });
        expect(accept.split(",")).toEqual(expect.arrayContaining([".png", ".jpg", ".jpeg", ".webp", ".gif"]));
    });

    it("does not add image formats for a non-vision model", () => {
        const accept = buildChatAccept({ ...DAILY, enableVision: false });
        expect(accept.split(",")).not.toContain(".png");
        expect(accept.split(",")).toContain(".ofd");
    });

    it("does not duplicate parser-supported images for a vision model", () => {
        const accept = buildChatAccept({ ...DAILY, enableEtl4lm: true, enableVision: true });
        expect(accept.split(",").filter((ext) => ext === ".png")).toHaveLength(1);
        expect(accept.split(",")).toEqual(expect.arrayContaining([".bmp", ".webp", ".gif"]));
    });
});

describe("isFileNameAccepted", () => {
    const accept = buildChatAccept({ ...DAILY, taskMode: true });

    it("matches by extension, case-insensitively", () => {
        expect(isFileNameAccepted("analyze.PY", accept)).toBe(true);
        // Test data, not UI copy: a non-ASCII basename must still match on suffix,
        // since the matcher lowercases the whole name before comparing.
        // eslint-disable-next-line no-restricted-syntax
        expect(isFileNameAccepted("数据表.csv", accept)).toBe(true);
    });

    it("rejects what the list does not name", () => {
        expect(isFileNameAccepted("setup.exe", accept)).toBe(false);
        expect(isFileNameAccepted("bundle.zip", accept)).toBe(false);
        expect(isFileNameAccepted("", accept)).toBe(false);
    });

    it("drives the leave-task-mode cleanup against the daily list", () => {
        const daily = buildChatAccept(DAILY);
        expect(isFileNameAccepted("analyze.py", daily)).toBe(false);
        expect(isFileNameAccepted("data.csv", daily)).toBe(false);
        expect(isFileNameAccepted("report.pdf", daily)).toBe(true);
    });

    it("rejects an attached image after switching to a non-vision model", () => {
        const vision = buildChatAccept({ ...DAILY, enableVision: true });
        const textOnly = buildChatAccept({ ...DAILY, enableVision: false });
        expect(isFileNameAccepted("diagram.webp", vision)).toBe(true);
        expect(isFileNameAccepted("diagram.webp", textOnly)).toBe(false);
    });

    it("treats an empty or wildcard accept as no restriction", () => {
        expect(isFileNameAccepted("anything.bin", "")).toBe(true);
        expect(isFileNameAccepted("anything.bin", "*")).toBe(true);
    });
});
