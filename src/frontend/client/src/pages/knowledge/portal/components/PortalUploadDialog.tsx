import type { Dispatch, MutableRefObject, ReactNode, SetStateAction } from "react";
import { ChevronDown, ChevronRight, FileText, Folder, Upload, X } from "lucide-react";
import {
    Button,
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "~/components/ui";
import type { PortalUploadFileItem, PortalUploadFolderNode, PortalUploadReviewRow, PortalUploadStep } from "../types";
import { formatFileSize } from "../utils";
import s from "../PortalKnowledgeWorkbench.module.css";

interface PortalUploadDialogProps {
    open: boolean;
    step: PortalUploadStep;
    activeSpaceName?: string;
    uploadInputRef: MutableRefObject<HTMLInputElement | null>;
    uploadFolderInputRef: MutableRefObject<HTMLInputElement | null>;
    uploadFiles: PortalUploadFileItem[];
    uploadLocalFolderName: string | null;
    uploadFolderId: string | null;
    uploadFolderName: string;
    uploadFolderNodes: PortalUploadFolderNode[];
    uploadFolderLoading: boolean;
    uploadSubmitting: boolean;
    uploadImporting: boolean;
    uploadReviewRows: PortalUploadReviewRow[];
    uploadFolderOptions: Array<{ id: string | null; name: string }>;
    onOpen: () => void;
    onClose: () => void;
    onAddUploadFiles: (files?: FileList | File[]) => void;
    onAddUploadFolder: (files?: FileList | File[]) => void;
    onRemoveUploadFile: (fileId: string) => void;
    onSelectUploadFolder: (folderId: string | null, folderName: string) => void;
    onToggleUploadFolder: (node: PortalUploadFolderNode) => void;
    onUploadNext: () => void;
    onReviewRowsChange: Dispatch<SetStateAction<PortalUploadReviewRow[]>>;
    onBackToSelect: () => void;
    onStartUploadImport: () => void;
}

function UploadFolderNode({
    node,
    depth,
    uploadFolderId,
    onToggleUploadFolder,
    onSelectUploadFolder,
}: {
    node: PortalUploadFolderNode;
    depth: number;
    uploadFolderId: string | null;
    onToggleUploadFolder: (node: PortalUploadFolderNode) => void;
    onSelectUploadFolder: (folderId: string | null, folderName: string) => void;
}): ReactNode {
    return (
        <div key={node.id}>
            <div className={s.uploadFolderRow} style={{ paddingLeft: `${8 + depth * 16}px` }}>
                <button
                    type="button"
                    className={s.uploadFolderExpandButton}
                    aria-label={`${node.expanded ? "收起" : "展开"}上传目录${node.name}`}
                    onClick={() => onToggleUploadFolder(node)}
                >
                    {node.expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                </button>
                <button
                    type="button"
                    className={`${s.uploadFolderSelectButton} ${uploadFolderId === node.id ? s.uploadFolderSelectButtonActive : ""}`}
                    aria-label={`选择上传目录${node.name}`}
                    onClick={() => onSelectUploadFolder(node.id, node.name)}
                >
                    <Folder size={14} />
                    <span>{node.name}</span>
                </button>
            </div>
            {node.expanded && node.loading ? (
                <div className={s.uploadFolderLoading} style={{ paddingLeft: `${30 + (depth + 1) * 16}px` }}>
                    加载中...
                </div>
            ) : null}
            {node.expanded ? node.children.map((child) => (
                <UploadFolderNode
                    key={child.id}
                    node={child}
                    depth={depth + 1}
                    uploadFolderId={uploadFolderId}
                    onToggleUploadFolder={onToggleUploadFolder}
                    onSelectUploadFolder={onSelectUploadFolder}
                />
            )) : null}
        </div>
    );
}

export function PortalUploadDialog({
    open,
    step,
    activeSpaceName,
    uploadInputRef,
    uploadFolderInputRef,
    uploadFiles,
    uploadLocalFolderName,
    uploadFolderId,
    uploadFolderName,
    uploadFolderNodes,
    uploadFolderLoading,
    uploadSubmitting,
    uploadImporting,
    uploadReviewRows,
    uploadFolderOptions,
    onOpen,
    onClose,
    onAddUploadFiles,
    onAddUploadFolder,
    onRemoveUploadFile,
    onSelectUploadFolder,
    onToggleUploadFolder,
    onUploadNext,
    onReviewRowsChange,
    onBackToSelect,
    onStartUploadImport,
}: PortalUploadDialogProps) {
    const selectedReviewCount = uploadReviewRows.filter((row) => row.selected).length;

    return (
        <Dialog
            open={open}
            onOpenChange={(nextOpen) => {
                if (!nextOpen) {
                    onClose();
                } else {
                    onOpen();
                }
            }}
        >
            {step === "select" ? (
                <DialogContent className={s.uploadDialogContent} onPointerDownOutside={(event) => event.preventDefault()}>
                    <div data-testid="portal-upload-dialog" className={s.uploadDialogInner}>
                        <DialogHeader>
                            <DialogTitle>上传文件</DialogTitle>
                        </DialogHeader>
                        <div className={s.uploadStepBody}>
                            <div className={s.uploadSection}>
                                <div className={s.uploadLabel}>选择文件</div>
                                <div
                                    className={s.uploadDropzone}
                                    onDragOver={(event) => {
                                        event.preventDefault();
                                    }}
                                    onDrop={(event) => {
                                        event.preventDefault();
                                        onAddUploadFiles(event.dataTransfer.files);
                                    }}
                                >
                                    <Upload size={34} />
                                    <span>点击选择文件或拖拽文件到此处</span>
                                    <small>支持多个文件同时上传</small>
                                    <div className={s.uploadPickActions}>
                                        <button
                                            type="button"
                                            className={s.uploadPickButton}
                                            onClick={() => uploadInputRef.current?.click()}
                                        >
                                            选择文件
                                        </button>
                                        <button
                                            type="button"
                                            className={s.uploadPickButton}
                                            onClick={() => uploadFolderInputRef.current?.click()}
                                        >
                                            选择文件夹
                                        </button>
                                    </div>
                                </div>
                                <input
                                    ref={uploadInputRef}
                                    aria-label="选择文件"
                                    className={s.uploadNativeInput}
                                    type="file"
                                    multiple
                                    onChange={(event) => {
                                        onAddUploadFiles(event.currentTarget.files || undefined);
                                        event.currentTarget.value = "";
                                    }}
                                />
                                <input
                                    ref={uploadFolderInputRef}
                                    aria-label="选择文件夹"
                                    className={s.uploadNativeInput}
                                    type="file"
                                    multiple
                                    onChange={(event) => {
                                        onAddUploadFolder(event.currentTarget.files || undefined);
                                        event.currentTarget.value = "";
                                    }}
                                    {...({ webkitdirectory: "", directory: "" } as any)}
                                />
                            </div>

                            <div className={s.uploadSection}>
                                <div className={s.uploadLabel}>上传位置</div>
                                <label className={s.uploadField}>
                                    <span>目标知识库</span>
                                    <input aria-label="目标知识库" className={s.uploadReadonlyInput} value={activeSpaceName || ""} readOnly />
                                </label>
                                <div className={s.uploadField}>
                                    <span>上传目标目录</span>
                                    <div className={s.uploadFolderPicker}>
                                        <div className={s.uploadFolderSelected} data-testid="selected-upload-folder">
                                            {uploadFolderName}
                                        </div>
                                        <div className={s.uploadFolderTree}>
                                            <div className={s.uploadFolderRow}>
                                                <span className={s.uploadFolderExpandPlaceholder} />
                                                <button
                                                    type="button"
                                                    className={`${s.uploadFolderSelectButton} ${uploadFolderId === null ? s.uploadFolderSelectButtonActive : ""}`}
                                                    aria-label="选择上传目录根目录"
                                                    onClick={() => onSelectUploadFolder(null, "根目录")}
                                                >
                                                    <Folder size={14} />
                                                    <span>选择根目录</span>
                                                </button>
                                            </div>
                                            {uploadFolderLoading ? (
                                                <div className={s.uploadFolderLoading}>目录加载中...</div>
                                            ) : uploadFolderNodes.length ? (
                                                uploadFolderNodes.map((node) => (
                                                    <UploadFolderNode
                                                        key={node.id}
                                                        node={node}
                                                        depth={0}
                                                        uploadFolderId={uploadFolderId}
                                                        onToggleUploadFolder={onToggleUploadFolder}
                                                        onSelectUploadFolder={onSelectUploadFolder}
                                                    />
                                                ))
                                            ) : (
                                                <div className={s.uploadFolderEmpty}>暂无子目录</div>
                                            )}
                                        </div>
                                    </div>
                                </div>
                                <div className={s.uploadHint}>
                                    文件将上传到所选知识空间目录，下一步会进入待入库确认。
                                </div>
                            </div>

                            {uploadFiles.length ? (
                                <div className={s.uploadSelectedFiles}>
                                    <div className={s.uploadLabel}>已选择的文件 ({uploadFiles.length})</div>
                                    {uploadLocalFolderName ? (
                                        <div className={s.uploadFolderNotice}>
                                            <strong>将创建文件夹：{uploadLocalFolderName}</strong>
                                            <span>仅上传所选文件夹根目录下的支持文件，子目录文件不会上传。</span>
                                        </div>
                                    ) : null}
                                    {uploadFiles.map((item) => (
                                        <div key={item.id} className={s.uploadSelectedFile}>
                                            <FileText size={16} />
                                            <div className={s.uploadFileMeta}>
                                                <span>{item.file.name}</span>
                                                <small>{formatFileSize(item.file.size)}</small>
                                            </div>
                                            <button
                                                type="button"
                                                className={s.uploadRemoveButton}
                                                aria-label={`移除${item.file.name}`}
                                                onClick={() => onRemoveUploadFile(item.id)}
                                            >
                                                <X size={16} />
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            ) : null}
                        </div>
                        <DialogFooter>
                            <Button variant="outline" className="h-8" onClick={onClose}>
                                取消
                            </Button>
                            <Button className="h-8" disabled={!uploadFiles.length || uploadSubmitting} onClick={onUploadNext}>
                                {uploadSubmitting ? "上传中..." : "下一步"}
                            </Button>
                        </DialogFooter>
                    </div>
                </DialogContent>
            ) : (
                <DialogContent className={s.uploadReviewContent} onPointerDownOutside={(event) => event.preventDefault()}>
                    <div data-testid="portal-upload-review-dialog" className={s.uploadReviewInner}>
                        <DialogHeader>
                            <DialogTitle>待入库确认</DialogTitle>
                        </DialogHeader>
                        <div className={s.uploadReviewToolbar}>
                            <input className={s.uploadReviewSearch} placeholder="搜索文档标题..." />
                            <button
                                type="button"
                                className={s.secondaryButton}
                                onClick={() => onReviewRowsChange((prev) => prev.map((row) => ({ ...row, selected: false })))}
                            >
                                取消全选
                            </button>
                            <span>已勾选 {selectedReviewCount} / {uploadReviewRows.length} 个文档</span>
                        </div>
                        <div className={s.uploadReviewTable}>
                            <div className={s.uploadReviewTableHead}>
                                <input
                                    type="checkbox"
                                    aria-label="选择全部待入库文件"
                                    checked={uploadReviewRows.length > 0 && selectedReviewCount === uploadReviewRows.length}
                                    onChange={(event) => {
                                        const checked = event.currentTarget.checked;
                                        onReviewRowsChange((prev) => prev.map((row) => ({ ...row, selected: checked })));
                                    }}
                                />
                                <span>标题</span>
                                <span>推荐存储路径</span>
                                <span>存储路径</span>
                                <span>版本管理</span>
                            </div>
                            {uploadReviewRows.length ? uploadReviewRows.map((row) => (
                                <div key={row.file.id} className={s.uploadReviewRow}>
                                    <input
                                        type="checkbox"
                                        aria-label={`选择${row.file.name}`}
                                        checked={row.selected}
                                        onChange={(event) => {
                                            const checked = event.currentTarget.checked;
                                            onReviewRowsChange((prev) => prev.map((item) => item.file.id === row.file.id ? {
                                                ...item,
                                                selected: checked,
                                            } : item));
                                        }}
                                    />
                                    <div className={s.uploadReviewTitle}>
                                        <small>{row.file.fileEncoding || "-"}</small>
                                        <span>{row.file.name}</span>
                                    </div>
                                    <span className={s.uploadReviewPath}>{row.recommendedFolderName}</span>
                                    <select
                                        className={s.uploadReviewSelect}
                                        aria-label={`${row.file.name}存储路径`}
                                        value={row.storageFolderId ?? ""}
                                        onChange={(event) => {
                                            const selectedValue = event.currentTarget.value;
                                            const nextId = selectedValue || null;
                                            const nextOption = uploadFolderOptions.find((option) => (option.id ?? "") === selectedValue);
                                            onReviewRowsChange((prev) => prev.map((item) => item.file.id === row.file.id ? {
                                                ...item,
                                                storageFolderId: nextId,
                                                storageFolderName: nextOption?.name || "根目录",
                                            } : item));
                                        }}
                                    >
                                        {uploadFolderOptions.map((option) => (
                                            <option key={option.id ?? "root"} value={option.id ?? ""}>
                                                {option.name}
                                            </option>
                                        ))}
                                    </select>
                                    <select
                                        className={s.uploadReviewSelect}
                                        aria-label={`${row.file.name}版本管理`}
                                        value={row.selectedTargetDocumentId ?? ""}
                                        onChange={(event) => {
                                            const selectedValue = event.currentTarget.value;
                                            const value = Number(selectedValue);
                                            onReviewRowsChange((prev) => prev.map((item) => item.file.id === row.file.id ? {
                                                ...item,
                                                selectedTargetDocumentId: Number.isFinite(value) && selectedValue ? value : null,
                                            } : item));
                                        }}
                                    >
                                        <option value="">
                                            {row.candidatesLoading ? "加载中..." : row.candidateError ? "推荐加载失败" : "不关联新版本"}
                                        </option>
                                        {row.candidates.map((candidate) => (
                                            <option key={candidate.target_document_id} value={candidate.target_document_id}>
                                                {candidate.title}
                                            </option>
                                        ))}
                                    </select>
                                </div>
                            )) : (
                                <div className={s.uploadReviewEmpty}>暂无待入库文件</div>
                            )}
                        </div>
                        <DialogFooter>
                            <Button variant="outline" className="h-8" disabled={uploadImporting} onClick={onBackToSelect}>
                                返回
                            </Button>
                            <Button className="h-8" disabled={selectedReviewCount === 0 || uploadImporting} onClick={onStartUploadImport}>
                                {uploadImporting ? "导入中..." : `开始导入 (${selectedReviewCount})`}
                            </Button>
                        </DialogFooter>
                    </div>
                </DialogContent>
            )}
        </Dialog>
    );
}
