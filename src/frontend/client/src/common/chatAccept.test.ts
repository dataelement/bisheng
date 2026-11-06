import { buildChatAccept, canProcessChatImage, isFileNameAccepted } from "./chatAccept";

const DAILY = { enableMedia: false, includeOfd: true };

describe("buildChatAccept", () => {
    it("accepts images before a processing capability is chosen", () => {
        const accept = buildChatAccept(DAILY);
        for (const extension of ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp']) {
            expect(isFileNameAccepted(`clipboard.${extension}`, accept)).toBe(true);
        }
        expect(isFileNameAccepted('report.pdf', accept)).toBe(true);
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

    it("keeps images and optional media in task mode", () => {
        const accept = buildChatAccept({
            enableMedia: true,
            includeOfd: true,
            taskMode: true,
        });
        expect(accept.split(",")).toEqual(expect.arrayContaining([".png", ".mp3", ".mp4", ".py"]));
    });

    it("allows backend-supported image formats for a vision model", () => {
        const accept = buildChatAccept({ ...DAILY, enableVision: true });
        expect(accept.split(",")).toEqual(expect.arrayContaining([".png", ".jpg", ".jpeg", ".webp", ".gif"]));
    });

    it("keeps image intake available for a non-vision model", () => {
        const accept = buildChatAccept({ ...DAILY, enableVision: false });
        expect(accept.split(",")).toContain(".png");
        expect(accept.split(",")).toContain(".ofd");
    });

    it("does not duplicate parser-supported images for a vision model", () => {
        const accept = buildChatAccept({ ...DAILY, enableEtl4lm: true, enableVision: true });
        expect(accept.split(",").filter((ext) => ext === ".png")).toHaveLength(1);
        expect(accept.split(",")).toEqual(expect.arrayContaining([".bmp", ".webp", ".gif"]));
    });

    it("keeps vision images accepted when leaving task mode", () => {
        const taskAccept = buildChatAccept({ ...DAILY, enableVision: true, taskMode: true });
        const dailyAccept = buildChatAccept({ ...DAILY, enableVision: true });
        for (const ext of [".png", ".jpg", ".jpeg", ".webp", ".gif"]) {
            expect(taskAccept.split(",")).toContain(ext);
            expect(dailyAccept.split(",")).toContain(ext);
        }
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

    it("checks image processing at send time after switching models", () => {
        const vision = buildChatAccept({ ...DAILY, enableVision: true });
        const textOnly = buildChatAccept({ ...DAILY, enableVision: false });
        expect(isFileNameAccepted("diagram.webp", vision)).toBe(true);
        expect(isFileNameAccepted("diagram.webp", textOnly)).toBe(true);
        expect(canProcessChatImage("diagram.webp", false, false)).toBe(false);
    });

    it("treats an empty or wildcard accept as no restriction", () => {
        expect(isFileNameAccepted("anything.bin", "")).toBe(true);
        expect(isFileNameAccepted("anything.bin", "*")).toBe(true);
    });
});

describe('image processing at send time', () => {
    test.each([
        ['image.png', false, false, false],
        ['image.png', true, false, true],
        ['image.png', false, true, true],
        ['image.WEBP', true, false, true],
        ['image.bmp', true, false, false],
        ['image.bmp', false, true, true],
        ['notes.txt', false, false, true],
    ])('%s vision=%s parser=%s yields %s', (name, vision, parser, expected) => {
        expect(canProcessChatImage(name, vision, parser)).toBe(expected);
    });
});
