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

    it("treats an empty or wildcard accept as no restriction", () => {
        expect(isFileNameAccepted("anything.bin", "")).toBe(true);
        expect(isFileNameAccepted("anything.bin", "*")).toBe(true);
    });
});
