import { extractKnowledgeFileError, FileStatus, FileType, type KnowledgeFile } from "~/api/knowledge";
import {
  extractDuplicateFileEntries,
  mergeVisibleRegisteredFiles,
  partitionUploadMutationResults,
  registerFolderStagesWithRetry,
  registerUploadedStagesWithRetry,
  retryApprovedUploadIngest,
} from "./fileUploadUtils";
import type { FileMutationItemResult } from "~/api/knowledge";

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
  test("mixed upload registration only exposes direct files to the formal list", () => {
    const directFile = makeKnowledgeFile({ id: "31", name: "direct.docx" });
    const results: FileMutationItemResult[] = [
      {
        inputId: "upload-direct",
        resourceType: "file",
        decision: "direct",
        resource: directFile,
      },
      {
        inputId: "upload-pending",
        resourceType: "file",
        decision: "pending",
        approvalInstanceId: 41,
        changeRequestId: 51,
      },
      {
        inputId: "upload-invalid",
        resourceType: "file",
        decision: "invalid",
        errorCode: 18072,
        errorMessage: "conflict",
      },
    ];

    expect(partitionUploadMutationResults(results)).toEqual({
      directFiles: [directFile],
      pending: [results[1]],
      invalid: [results[2]],
    });
  });

  test("registration timeout retries once with the same opaque upload ids", async () => {
    const response: FileMutationItemResult[] = [
      {
        inputId: "upload-stable",
        resourceType: "file",
        decision: "pending",
        approvalInstanceId: 61,
        changeRequestId: 71,
      },
    ];
    const register = jest
      .fn<Promise<FileMutationItemResult[]>, [string, { upload_ids: string[]; parent_id?: number | null }]>()
      .mockRejectedValueOnce(new Error("timeout"))
      .mockResolvedValueOnce(response);

    await expect(
      registerUploadedStagesWithRetry({
        spaceId: "9",
        uploadIds: ["upload-stable"],
        parentId: 3,
        register,
      }),
    ).resolves.toEqual(response);

    expect(register).toHaveBeenCalledTimes(2);
    expect(register.mock.calls[0]).toEqual([
      "9",
      { upload_ids: ["upload-stable"], parent_id: 3 },
    ]);
    expect(register.mock.calls[1]).toEqual(register.mock.calls[0]);
  });

  test("a new multipart upload registers its newly issued upload id", async () => {
    const register = jest
      .fn<Promise<FileMutationItemResult[]>, [string, { upload_ids: string[]; parent_id?: number | null }]>()
      .mockResolvedValue([]);

    await registerUploadedStagesWithRetry({
      spaceId: "9",
      uploadIds: ["upload-new-content"],
      parentId: null,
      register,
    });

    expect(register).toHaveBeenCalledWith("9", {
      upload_ids: ["upload-new-content"],
      parent_id: null,
    });
  });

  test("folder registration retry preserves upload ids and relative paths", async () => {
    const items = [{ upload_id: "folder-stage", relative_path: "Docs/a.pdf" }];
    const register = jest
      .fn<Promise<FileMutationItemResult[]>, [string, { parent_id?: number | null; items: typeof items }]>()
      .mockRejectedValueOnce(new Error("timeout"))
      .mockResolvedValueOnce([]);

    await registerFolderStagesWithRetry({
      spaceId: "9",
      items,
      parentId: null,
      register,
    });

    expect(register).toHaveBeenCalledTimes(2);
    expect(register.mock.calls[0]).toEqual(["9", { parent_id: null, items }]);
    expect(register.mock.calls[1]).toEqual(register.mock.calls[0]);
  });

  test("parse retry reuses the approved request instead of registering an upload", async () => {
    const retry = jest.fn().mockResolvedValue({ requestId: 71, status: "parsing" });

    await retryApprovedUploadIngest("9", 71, retry);

    expect(retry).toHaveBeenCalledTimes(1);
    expect(retry).toHaveBeenCalledWith("9", 71);
  });

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

  test("extractKnowledgeFileError formats missing knowledge-base ASR configuration", () => {
    const remark = JSON.stringify({
      status_code: 10014,
      status_message: "Knowledge base ASR model is not configured",
      data: {
        exception: "Knowledge base ASR model is not configured",
      },
    });

    expect(extractKnowledgeFileError({ remark })).toBe(
      "未配置知识库语音转文字（ASR）模型，请在「系统模型设置 → 知识库模型」中配置后再上传音视频。",
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
