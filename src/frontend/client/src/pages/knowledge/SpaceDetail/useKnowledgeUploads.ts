import type { UseKnowledgeUploadsOptions } from "./knowledgeSpaceTypes";
import { extractApiStatusCode } from "~/utils/apiStatusError";
import { useState, useRef, useEffect, type MouseEvent } from "react";
import { importWebLinkApi } from "~/api/knowledge";
import { useFileDragDrop } from "../hooks/useFileDragDrop";
import { dispatchKnowledgeSpaceFilesRefresh } from "../hooks/useFileManager";
import {
  getMaxFileSizeBytesForFile,
  getMaxFileSizeMBForFile,
} from "../knowledgeUtils";
import { resolveLocalizedKnowledgeImportError } from "../webLinkI18n";
import { knowledgeUploadCapabilities } from "../knowledgeUploadCapabilities";

function normalizeWebLinkTitle(title: string): string | undefined {
  const trimmed = title.trim();
  if (!trimmed) return undefined;
  return /\.html$/i.test(trimmed) ? trimmed : `${trimmed}.html`;
}

export function useKnowledgeUploads({
  localize,
  setContextMenuOpen,
  setContextMenuPosition,
  queryClient,
  canUploadFile,
  canUseContextMenuActions,
  showToast,
  confirm,
  isStorageBlocked,
  refreshQuota,
  uploadSizeLimits,
  maxFileSizeMB,
  enableEtl4lm,
  allowedExtensions,
  space,
  onUploadFile,
  onUploadFolder,
  onDeleteFile,
  currentFolderId,
  onDragStateChange,
}: UseKnowledgeUploadsOptions) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  const triggerUpload = () => {
    if (!canUploadFile) return;
    fileInputRef.current?.click();
  };

  const triggerUploadFolder = () => {
    if (!canUploadFile) return;
    folderInputRef.current?.click();
  };

  const [webLinkDialogOpen, setWebLinkDialogOpen] = useState(false);
  const [webLinkUrl, setWebLinkUrl] = useState("");
  const [webLinkTitle, setWebLinkTitle] = useState("");
  const [webLinkSubmitting, setWebLinkSubmitting] = useState(false);

  const triggerWebLink = () => {
    if (!knowledgeUploadCapabilities.webLink || !canUploadFile) return;
    setWebLinkDialogOpen(true);
  };

  const refreshAfterWebLinkImport = () => {
    queryClient.invalidateQueries({ queryKey: ["file-versions"] });
    dispatchKnowledgeSpaceFilesRefresh(space.id);
    onDeleteFile("");
    void refreshQuota();
  };

  const resetWebLinkDialog = () => {
    setWebLinkUrl("");
    setWebLinkTitle("");
  };

  const submitWebLink = async (overwrite = false) => {
    if (isStorageBlocked()) return;
    const trimmedUrl = webLinkUrl.trim();
    const normalizedTitle = normalizeWebLinkTitle(webLinkTitle);
    if (!trimmedUrl) {
      showToast({
        message: localize("com_knowledge.web_link_url_required"),
        status: "warning",
      });
      return;
    }
    try {
      const parsed = new URL(trimmedUrl);
      if (!["http:", "https:"].includes(parsed.protocol)) {
        showToast({
          message: localize("com_knowledge.web_link_http_only"),
          status: "warning",
        });
        return;
      }
    } catch {
      showToast({
        message: localize("com_knowledge.web_link_invalid"),
        status: "warning",
      });
      return;
    }

    setWebLinkSubmitting(true);
    try {
      await importWebLinkApi(space.id, {
        url: trimmedUrl,
        title: normalizedTitle,
        parent_id: currentFolderId ? Number(currentFolderId) : null,
        overwrite,
      });
      showToast({
        message: localize("com_knowledge.web_link_import_success"),
        status: "success",
      });
      setWebLinkDialogOpen(false);
      resetWebLinkDialog();
      refreshAfterWebLinkImport();
    } catch (error: unknown) {
      const statusCode = extractApiStatusCode(error);
      if (!overwrite && (statusCode === 18021 || statusCode === 18023)) {
        const confirmed = await confirm({
          description: localize(
            statusCode === 18021
              ? "com_knowledge.web_link_duplicate_content_confirm"
              : "com_knowledge.web_link_duplicate_name_confirm",
          ),
          confirmText: localize("com_knowledge.overwrite"),
          cancelText: localize("com_knowledge.cancel"),
        });
        if (confirmed) {
          await submitWebLink(true);
        }
        return;
      }
      showToast({
        message: resolveLocalizedKnowledgeImportError(
          error,
          localize,
          "com_knowledge.web_link_import_failed",
        ),
        status: "warning",
      });
    } finally {
      setWebLinkSubmitting(false);
    }
  };

  useEffect(() => {
    if (!canUseContextMenuActions) {
      setContextMenuOpen(false);
    }
  }, [canUseContextMenuActions, setContextMenuOpen]);

  const handleContentContextMenu = (e: MouseEvent<HTMLDivElement>) => {
    if (!canUseContextMenuActions) return;
    const target = e.target;
    if (
      target instanceof Element &&
      target.closest("[data-knowledge-file-item]")
    )
      return;

    e.preventDefault();
    setContextMenuPosition({ x: e.clientX, y: e.clientY });
    setContextMenuOpen(true);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const filesList = Array.from(e.target.files);

      if (filesList.length > 50) {
        showToast({
          message: localize("com_knowledge.max_upload_50"),
          status: "warning",
        });
        if (fileInputRef.current) fileInputRef.current.value = "";
        return;
      }

      for (const f of filesList) {
        const fileMaxSizeMB = getMaxFileSizeMBForFile(f.name, uploadSizeLimits);
        const fileMaxSizeBytes = getMaxFileSizeBytesForFile(
          f.name,
          uploadSizeLimits,
        );
        if (f.size > fileMaxSizeBytes) {
          showToast({
            message: localize("com_knowledge.file_exceeds_limit", {
              name: f.name,
              size: fileMaxSizeMB,
            }),
            status: "warning",
          });
          if (fileInputRef.current) fileInputRef.current.value = "";
          return;
        }
        const ext = f.name.split(".").pop()?.toLowerCase();
        if (!ext || !allowedExtensions.includes(ext)) {
          showToast({
            message: localize("com_knowledge.unsupported_file_format", {
              0: f.name,
            }),
            status: "warning",
          });
          if (fileInputRef.current) fileInputRef.current.value = "";
          return;
        }
      }

      if (canUploadFile) {
        onUploadFile(filesList);
      }
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  // Folder upload: hand the full FileList to the hook, which handles
  // hidden-folder rejection, dup-name check, count cap, and silent filtering
  // (oversize / unsupported / hidden) — see useFileUpload.handleUploadFolder.
  const handleFolderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const filesList = e.target.files;
    if (filesList && filesList.length > 0 && canUploadFile) {
      onUploadFolder(filesList, {
        allowedExtensions,
        maxSizeMB: maxFileSizeMB,
        limits: uploadSizeLimits,
      });
    }
    if (folderInputRef.current) folderInputRef.current.value = "";
  };

  // ─── Drag and drop ──────────────────────────────────────────────────
  const { handleDragEnter, handleDragLeave, handleDragOver, handleDrop } =
    useFileDragDrop({
      onDragStateChange,
      onUploadFile: canUploadFile ? onUploadFile : () => undefined,
      // Without this the folder-drop branch in handleDrop is skipped (it
      // guards on `onUploadFolder` being defined), so dropping a folder did
      // nothing. Gate on canUploadFile like onUploadFile.
      onUploadFolder: canUploadFile ? onUploadFolder : undefined,
      maxFileSizeMB,
      uploadSizeLimits,
      enableEtl4lm,
    });

  return {
    fileInputRef,
    folderInputRef,
    triggerUpload,
    triggerUploadFolder,
    webLinkDialogOpen,
    setWebLinkDialogOpen,
    webLinkUrl,
    setWebLinkUrl,
    webLinkTitle,
    setWebLinkTitle,
    webLinkSubmitting,
    triggerWebLink,
    resetWebLinkDialog,
    submitWebLink,
    handleContentContextMenu,
    handleFileChange,
    handleFolderChange,
    handleDragEnter,
    handleDragLeave,
    handleDragOver,
    handleDrop,
  };
}
