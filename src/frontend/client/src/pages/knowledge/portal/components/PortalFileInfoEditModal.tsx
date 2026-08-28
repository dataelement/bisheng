import {
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
    type ChangeEvent,
    type KeyboardEvent,
} from "react";
import { Loader2, Pencil } from "lucide-react";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    Input,
} from "~/components/ui";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import { getFullWidthLength } from "~/utils";
import {
    checkSensitiveWordsApi,
    FileStatus,
    FileType,
    isWebLinkKnowledgeFile,
    renameFileApi,
    resolveWebLinkDisplayName,
    toWebLinkFileName,
    type KnowledgeFile,
} from "~/api/knowledge";
import { PortalFileCategoryDropdown } from "./PortalFileCategoryDropdown";
import type { PortalFileCategoryGroupOption, PortalFileSubcategoryOption } from "../types";
import {
    joinEditableFileName,
    splitEditableFileName,
} from "../../hooks/useInlineRename";
import {
    type BusinessDomainOptionItem,
    composeFileEncoding,
    fileEncodingBusinessDomainLabel,
    normalizeEncodingCode,
    parseFileEncoding,
    resolveFileBusinessDomainCode,
} from "../uploadMetadata";
import s from "../PortalKnowledgeWorkbench.module.css";

interface PortalFileInfoEditModalProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    file: KnowledgeFile;
    spaceId: string;
    fileCategoryGroups: PortalFileCategoryGroupOption[];
    businessDomainOptions: BusinessDomainOptionItem[];
    encodingPrefix: string;
    canEdit: boolean;
    onFileUpdated: (updater: (file: KnowledgeFile) => KnowledgeFile) => void;
    onUpdateEncoding: (
        newEncoding: string,
        fileSubcategoryCode?: string | null,
    ) => void | Promise<void>;
}

export function PortalFileInfoEditModal({
    open,
    onOpenChange,
    file,
    spaceId,
    fileCategoryGroups,
    businessDomainOptions,
    encodingPrefix,
    canEdit,
    onFileUpdated,
    onUpdateEncoding,
}: PortalFileInfoEditModalProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();

    const isFolder = file.type === FileType.FOLDER;
    const isWebLink = isWebLinkKnowledgeFile(file);
    const { base: initialBase, ext } = useMemo(
        () => splitEditableFileName(file.name, isFolder),
        [file.name, isFolder],
    );

    const [renaming, setRenaming] = useState(false);
    const [renameValue, setRenameValue] = useState(initialBase);
    const [renameSaving, setRenameSaving] = useState(false);
    const renameInputRef = useRef<HTMLInputElement>(null);

    const [savingCategory, setSavingCategory] = useState(false);
    const [savingDomain, setSavingDomain] = useState(false);

    useEffect(() => {
        setRenameValue(initialBase);
    }, [initialBase]);

    useEffect(() => {
        if (open) {
            setRenaming(false);
            setRenameSaving(false);
            setRenameValue(initialBase);
        }
    }, [open, initialBase]);

    useEffect(() => {
        if (renaming && renameInputRef.current) {
            const input = renameInputRef.current;
            input.focus();
            const timerId = setTimeout(() => {
                input.select();
            }, 10);
            return () => clearTimeout(timerId);
        }
    }, [renaming]);

    const parsedEncoding = useMemo(
        () => parseFileEncoding(file.fileEncoding, encodingPrefix),
        [file.fileEncoding, encodingPrefix],
    );
    const selectedFileCategoryCode = normalizeEncodingCode(parsedEncoding.fileCategoryCode);
    const selectedBusinessDomainCode = resolveFileBusinessDomainCode(
        file,
        undefined,
        encodingPrefix,
    );
    const hasCurrentBusinessDomainOption = businessDomainOptions.some(
        (option) => option.code === selectedBusinessDomainCode,
    );
    const isBusinessDomainLocked = file.status === FileStatus.PROCESSING;

    const validateName = useCallback(
        (name: string) => {
            const trimmed = name.trim();
            if (!trimmed) {
                return localize("com_knowledge.name_empty");
            }
            if (getFullWidthLength(trimmed) > 50) {
                return localize("com_knowledge.name_max_50");
            }
            return null;
        },
        [localize],
    );

    const handleRenameSubmit = useCallback(async () => {
        if (renameSaving) return;
        const trimmed = renameValue.trim();
        const error = validateName(trimmed);
        if (error) {
            showToast({ message: error, severity: NotificationSeverity.ERROR });
            renameInputRef.current?.focus();
            return;
        }
        if (trimmed === initialBase) {
            setRenaming(false);
            return;
        }

        const fullName = joinEditableFileName(trimmed, ext);
        setRenameSaving(true);
        try {
            const sensitiveCheck = await checkSensitiveWordsApi(spaceId, [fullName]);
            if (sensitiveCheck.has_violation) {
                showToast({
                    message: localize("com_knowledge.name_contains_sensitive_words"),
                    severity: NotificationSeverity.ERROR,
                });
                renameInputRef.current?.focus();
                return;
            }

            const apiName = isWebLink ? toWebLinkFileName(fullName) : fullName;
            const displayName = isWebLink
                ? resolveWebLinkDisplayName(apiName, file.userMetadata)
                : fullName;

            await renameFileApi(spaceId, file.id, apiName);
            onFileUpdated((prev) => ({
                ...prev,
                name: displayName,
                aliasName: undefined,
                ...(isWebLink && prev.userMetadata
                    ? {
                        userMetadata: {
                            ...prev.userMetadata,
                            web_title: displayName,
                        },
                    }
                    : {}),
            }));
            showToast({
                message: localize("com_knowledge.rename_success"),
                severity: NotificationSeverity.SUCCESS,
            });
            setRenaming(false);
        } catch {
            showToast({
                message: localize("com_knowledge.rename_failed"),
                severity: NotificationSeverity.ERROR,
            });
        } finally {
            setRenameSaving(false);
        }
    }, [
        renameSaving,
        renameValue,
        initialBase,
        ext,
        spaceId,
        file.id,
        file.userMetadata,
        isWebLink,
        validateName,
        onFileUpdated,
        showToast,
        localize,
    ]);

    const handleRenameKeyDown = useCallback(
        (e: KeyboardEvent<HTMLInputElement>) => {
            if (e.key === "Enter") {
                e.preventDefault();
                void handleRenameSubmit();
            } else if (e.key === "Escape") {
                setRenameValue(initialBase);
                setRenaming(false);
            }
        },
        [handleRenameSubmit, initialBase],
    );

    const handleCategoryChange = useCallback(
        async (option: PortalFileSubcategoryOption | null) => {
            if (!option || savingCategory) return;
            const nextCategoryCode = normalizeEncodingCode(option.parentCode);
            const nextSubcategoryCode = normalizeEncodingCode(option.code);
            const businessDomainCode = resolveFileBusinessDomainCode(
                file,
                undefined,
                encodingPrefix,
            );
            if (!nextCategoryCode || !businessDomainCode) return;

            const newEncoding = composeFileEncoding(
                file.fileEncoding,
                nextCategoryCode,
                businessDomainCode,
                encodingPrefix,
            );
            const subcategoryChanged =
                nextSubcategoryCode !== normalizeEncodingCode(file.fileSubcategoryCode);
            if (newEncoding === file.fileEncoding?.trim() && !subcategoryChanged) return;

            setSavingCategory(true);
            try {
                await onUpdateEncoding(newEncoding, nextSubcategoryCode);
            } finally {
                setSavingCategory(false);
            }
        },
        [savingCategory, file, encodingPrefix, onUpdateEncoding],
    );

    const handleDomainChange = useCallback(
        async (event: ChangeEvent<HTMLSelectElement>) => {
            const code = event.currentTarget.value;
            if (!code || savingDomain || isBusinessDomainLocked) return;
            const categoryCode = normalizeEncodingCode(parsedEncoding.fileCategoryCode);
            if (!categoryCode) return;

            const newEncoding = composeFileEncoding(
                file.fileEncoding,
                categoryCode,
                code,
                encodingPrefix,
            );
            if (newEncoding === file.fileEncoding?.trim()) return;

            setSavingDomain(true);
            try {
                await onUpdateEncoding(newEncoding);
            } finally {
                setSavingDomain(false);
            }
        },
        [savingDomain, isBusinessDomainLocked, parsedEncoding, file, encodingPrefix, onUpdateEncoding],
    );

    const domainSelectClassName =
        "h-10 w-full min-w-0 rounded-lg border border-input bg-transparent px-3 text-sm text-[#4e5969] outline-none transition-colors focus:border-[#165dff] disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-[#f7f8fa] disabled:text-[#86909c]";

    const isLoading = renameSaving || savingCategory || savingDomain;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[520px]">
                <DialogHeader>
                    <DialogTitle>修改信息</DialogTitle>
                </DialogHeader>
                <div className={s.infoEditModalBody}>
                    {isLoading ? (
                        <div className={s.infoEditModalOverlay}>
                            <Loader2
                                size={24}
                                className="animate-spin text-[#165dff]"
                            />
                        </div>
                    ) : null}
                    <div className={s.infoEditModalRow}>
                        <div className={s.infoEditModalLabelWrap}>
                            <label className={s.infoEditModalLabel}>文件名称</label>
                            <span className={s.infoEditRenameHint}>
                                * 编辑完成之后进行回车保存
                            </span>
                        </div>
                        <div className={s.infoEditModalField}>
                            {renaming ? (
                                <div className={s.infoEditRenameWrap}>
                                    <Input
                                        ref={renameInputRef}
                                        type="text"
                                        value={renameValue}
                                        disabled={renameSaving || !canEdit}
                                        onChange={(e: ChangeEvent<HTMLInputElement>) => setRenameValue(e.target.value)}
                                        onBlur={() => void handleRenameSubmit()}
                                        onKeyDown={handleRenameKeyDown}
                                        className={s.infoEditRenameInput}
                                    />
                                    {ext ? (
                                        <span className={s.infoEditRenameExt}>{ext}</span>
                                    ) : null}
                                    {renameSaving ? (
                                        <Loader2
                                            size={16}
                                            className="animate-spin text-[#165dff]"
                                        />
                                    ) : null}
                                </div>
                            ) : (
                                <div className={s.infoEditRenameDisplay}>
                                    <span
                                        className={s.infoEditRenameName}
                                        title={file.name}
                                    >
                                        {file.name}
                                    </span>
                                    {canEdit ? (
                                        <button
                                            type="button"
                                            className={s.infoEditRenameButton}
                                            title="修改文件名"
                                            aria-label="修改文件名"
                                            onClick={() => setRenaming(true)}
                                        >
                                            <Pencil size={14} />
                                        </button>
                                    ) : null}
                                </div>
                            )}
                        </div>
                    </div>

                    <div className={s.infoEditModalRow}>
                        <label className={s.infoEditModalLabel}>文件分类</label>
                        <div className={s.infoEditModalField}>
                            <PortalFileCategoryDropdown
                                groups={fileCategoryGroups}
                                value={file.fileSubcategoryCode}
                                fallbackParentCode={selectedFileCategoryCode}
                                disabled={savingCategory || !canEdit}
                                variant="default"
                                ariaLabel="修改文件分类"
                                onChange={handleCategoryChange}
                            />
                        </div>
                    </div>

                    <div className={s.infoEditModalRow}>
                        <label className={s.infoEditModalLabel}>业务域</label>
                        <div className={s.infoEditModalField}>
                            <span
                                className="block w-full min-w-0"
                                title={
                                    isBusinessDomainLocked
                                        ? "文档解析中无法更改"
                                        : undefined
                                }
                            >
                                <select
                                    className={domainSelectClassName}
                                    aria-label={`修改业务域 当前业务域：${
                                        selectedBusinessDomainCode || "未识别"
                                    }`}
                                    value={selectedBusinessDomainCode}
                                    disabled={
                                        savingDomain || isBusinessDomainLocked || !canEdit
                                    }
                                    onChange={(event: ChangeEvent<HTMLSelectElement>) => void handleDomainChange(event)}
                                >
                                    {!selectedBusinessDomainCode ? (
                                        <option value="" disabled>
                                            --
                                        </option>
                                    ) : null}
                                    {selectedBusinessDomainCode &&
                                    !hasCurrentBusinessDomainOption ? (
                                        <option value={selectedBusinessDomainCode}>
                                            {fileEncodingBusinessDomainLabel(
                                                selectedBusinessDomainCode,
                                                businessDomainOptions,
                                            )}
                                        </option>
                                    ) : null}
                                    {businessDomainOptions.map((option) => (
                                        <option key={option.code} value={option.code}>
                                            {option.code} / {option.name}
                                        </option>
                                    ))}
                                </select>
                            </span>
                        </div>
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
}
