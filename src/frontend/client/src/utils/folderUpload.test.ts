import {
    checkFolderBatch,
    extractDroppedDirectories,
    getFileRelativePath,
    getFolderDepth,
    readFolderFilesRecursive,
    TASK_MODE_MAX_FOLDER_DEPTH,
    TASK_MODE_MAX_FOLDER_FILES,
    TASK_MODE_MAX_FOLDER_TOTAL_BYTES,
} from "./folderUpload";

/** A File with the relative path the `webkitdirectory` picker would stamp. */
function makeFile(name: string, relativePath?: string, size = 1): File {
    // `size` is stamped rather than materialized — the size cases run to
    // hundreds of MB and jsdom would try to allocate every byte.
    const file = new File(["x"], name);
    if (relativePath) {
        Object.defineProperty(file, "webkitRelativePath", { value: relativePath, configurable: true });
    }
    Object.defineProperty(file, "size", { value: size, configurable: true });
    return file;
}

/**
 * Minimal Entries-API fakes. `readEntries` deliberately yields its children in
 * two batches so the reader's "call until empty" loop is actually exercised —
 * a single-batch fake would pass even with the loop removed.
 */
type FakeTree = { [name: string]: FakeTree | null };

function makeDirEntry(name: string, tree: FakeTree): FileSystemDirectoryEntry {
    const children = Object.entries(tree).map(([childName, sub]) =>
        sub === null ? makeFileEntry(childName) : makeDirEntry(childName, sub),
    );
    return {
        name,
        isFile: false,
        isDirectory: true,
        createReader: () => {
            let cursor = 0;
            return {
                readEntries: (onOk: (batch: unknown[]) => void) => {
                    // one child per batch, then an empty batch to terminate
                    const batch = cursor < children.length ? [children[cursor]] : [];
                    cursor += 1;
                    onOk(batch);
                },
            };
        },
    } as unknown as FileSystemDirectoryEntry;
}

function makeFileEntry(name: string) {
    return {
        name,
        isFile: true,
        isDirectory: false,
        file: (onOk: (f: File) => void) => onOk(new File(["x"], name)),
    };
}

describe("getFileRelativePath / getFolderDepth", () => {
    test("a picked folder file keeps its relative path", () => {
        expect(getFileRelativePath(makeFile("Q1.xlsx", "Reports/2024/Q1.xlsx"))).toBe("Reports/2024/Q1.xlsx");
    });

    test("a loose file falls back to its bare name", () => {
        expect(getFileRelativePath(makeFile("report.pdf"))).toBe("report.pdf");
    });

    test("depth counts directories, not the file itself", () => {
        expect(getFolderDepth("report.pdf")).toBe(0);
        expect(getFolderDepth("docs/report.pdf")).toBe(1);
        expect(getFolderDepth("Reports/2024/Q1.xlsx")).toBe(2);
    });
});

describe("checkFolderBatch", () => {
    test("accepts a batch inside every limit", () => {
        const result = checkFolderBatch([makeFile("a.pdf", "docs/a.pdf"), makeFile("b.pdf", "docs/b.pdf")]);
        expect(result.rejection).toBeUndefined();
        expect(result.fileCount).toBe(2);
        expect(result.maxDepth).toBe(1);
    });

    test("rejects on file count", () => {
        const files = Array.from({ length: TASK_MODE_MAX_FOLDER_FILES + 1 }, (_, i) =>
            makeFile(`${i}.pdf`, `docs/${i}.pdf`),
        );
        expect(checkFolderBatch(files).rejection).toBe("count");
    });

    test("rejects on total size", () => {
        const half = Math.floor(TASK_MODE_MAX_FOLDER_TOTAL_BYTES / 2) + 1;
        const files = [makeFile("a.pdf", "docs/a.pdf", half), makeFile("b.pdf", "docs/b.pdf", half)];
        expect(checkFolderBatch(files).rejection).toBe("size");
    });

    test("rejects on nesting depth", () => {
        const deep = Array.from({ length: TASK_MODE_MAX_FOLDER_DEPTH + 1 }, (_, i) => `d${i}`).join("/");
        expect(checkFolderBatch([makeFile("f.pdf", `${deep}/f.pdf`)]).rejection).toBe("depth");
    });

    test("exactly at the depth limit is accepted", () => {
        const deep = Array.from({ length: TASK_MODE_MAX_FOLDER_DEPTH }, (_, i) => `d${i}`).join("/");
        expect(checkFolderBatch([makeFile("f.pdf", `${deep}/f.pdf`)]).rejection).toBeUndefined();
    });
});

describe("readFolderFilesRecursive", () => {
    test("flattens a nested tree and stamps each file's relative path", async () => {
        const dir = makeDirEntry("Reports", {
            "overview.md": null,
            "2024": { "Q1.xlsx": null, "Q2.xlsx": null },
        });

        const files = await readFolderFilesRecursive(dir, "");
        const paths = files.map(getFileRelativePath).sort();

        expect(paths).toEqual(["Reports/2024/Q1.xlsx", "Reports/2024/Q2.xlsx", "Reports/overview.md"]);
    });

    test("an empty directory resolves to no files rather than hanging", async () => {
        expect(await readFolderFilesRecursive(makeDirEntry("empty", {}), "")).toEqual([]);
    });
});

describe("extractDroppedDirectories", () => {
    const asItem = (entry: unknown) => ({ webkitGetAsEntry: () => entry });

    test("returns only the directory entries", () => {
        const dir = makeDirEntry("docs", {});
        const items = [asItem(makeFileEntry("loose.pdf")), asItem(dir)];
        const dataTransfer = { items: Object.assign(items, { length: items.length }) } as unknown as DataTransfer;

        expect(extractDroppedDirectories(dataTransfer)).toEqual([dir]);
    });

    test("is safe on engines without the Entries API", () => {
        const items = [{}];
        const dataTransfer = { items: Object.assign(items, { length: 1 }) } as unknown as DataTransfer;

        expect(extractDroppedDirectories(dataTransfer)).toEqual([]);
        expect(extractDroppedDirectories(null)).toEqual([]);
    });
});
