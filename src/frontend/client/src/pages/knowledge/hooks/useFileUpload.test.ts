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

  test("extractKnowledgeFileError formats no recognizable audio failures", () => {
    const remark = JSON.stringify({
      status_code: 10956,
      status_message: "No recognizable audio detected",
      data: {
        exception: "No recognizable audio detected",
      },
    });

    expect(extractKnowledgeFileError({ remark })).toBe(
      "未检测到可识别音频，无法生成识别文本。请上传包含清晰人声的音频或视频文件。",
    );
  });

  test("extractKnowledgeFileError formats legacy media extraction failures", () => {
    const remark = JSON.stringify({
      status_code: 10954,
      status_message: "Media transcription failed",
      data: {
        exception: "Media audio extraction failed",
      },
    });

    expect(extractKnowledgeFileError({ remark })).toBe(
      "未检测到可识别音频，无法生成识别文本。请上传包含清晰人声的音频或视频文件。",
    );
  });

  test("extractKnowledgeFileError formats sensitive check hits for violation detail", () => {
    const remark = JSON.stringify({
      reason: "sensitive_check",
      auto_reply: "不展示这段话",
      hits: [
        { word: "违禁词A", count: 2 },
        { word: "违禁词B", count: 1 },
        { word: "违禁词A", count: 1 },
      ],
    });

    expect(extractKnowledgeFileError({ remark })).toBe(
      "您上传的文件包含违规内容：{违禁词A,违禁词B}，请修改后重试",
    );
  });
});
