import { extractKnowledgeFileError, FileStatus, FileType, type KnowledgeFile } from "~/api/knowledge";
import {
  extractDuplicateFileEntries,
  mergeVisibleRegisteredFiles,
} from "./useFileUpload";

function makeKnowledgeFile(overrides: Partial<KnowledgeFile>): KnowledgeFile {
  return {
    id: "1",
    name: "demo.docx",
    type: FileType.DOCX,
    tags: [],
    path: "demo.docx",
    spaceId: "9",
    createdAt: "2026-04-20T00:00:00Z",
    updatedAt: "2026-04-20T00:00:00Z",
    ...overrides,
  };
}

describe("useFileUpload helpers", () => {
  test("extractDuplicateFileEntries only returns real duplicate conflicts", () => {
    const duplicateFile = makeKnowledgeFile({
      id: "11",
      name: "duplicate.docx",
      status: FileStatus.FAILED,
      oldFileLevelPath: "/root/folder",
    }) as KnowledgeFile & { _raw: Record<string, unknown> };
    duplicateFile._raw = { id: 11 };

    const parseFailedFile = makeKnowledgeFile({
      id: "12",
      name: "parse-failed.docx",
      status: FileStatus.FAILED,
      errorMessage: "parse failed",
    }) as KnowledgeFile & { _raw: Record<string, unknown> };
    parseFailedFile._raw = { id: 12 };

    expect(extractDuplicateFileEntries([duplicateFile, parseFailedFile])).toEqual([
      {
        fileId: "11",
        fileName: "duplicate.docx",
        oldFileLevelPath: "/root/folder",
        rawObj: { id: 11 },
      },
    ]);
  });

  test("mergeVisibleRegisteredFiles prepends new files without duplicating existing ids", () => {
    const existingFile = makeKnowledgeFile({
      id: "21",
      name: "existing.docx",
      status: FileStatus.SUCCESS,
    });
    const newWaitingFile = makeKnowledgeFile({
      id: "22",
      name: "new.docx",
      status: FileStatus.WAITING,
    });
    const duplicateExistingFile = makeKnowledgeFile({
      id: "21",
      name: "existing.docx",
      status: FileStatus.SUCCESS,
    });

    expect(
      mergeVisibleRegisteredFiles([existingFile], [newWaitingFile, duplicateExistingFile]),
    ).toEqual({
      files: [newWaitingFile, existingFile],
      addedCount: 1,
    });
  });

  test("extractKnowledgeFileError replaces status_message placeholders from nested data", () => {
    const remark = JSON.stringify({
      status_code: 10953,
      status_message: "File parsing failed: {exception}",
      data: {
        exception: "File parsing failed: {exception}",
        data: {
          exception: "rebuild error",
        },
      },
    });

    expect(extractKnowledgeFileError({ remark })).toBe("File parsing failed: rebuild error");
  });
});
