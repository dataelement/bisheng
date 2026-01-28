"use client"

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogPortal } from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { AlertCircle, CircleQuestionMark, Clock3, Edit2, Hash, Plus, SquarePen, Trash2, Type, X } from "lucide-react"
import React, { useCallback, useState, useRef, useEffect, memo, useMemo } from "react"
import * as DialogPrimitive from "@radix-ui/react-dialog"
import { cname } from "@/components/bs-ui/utils"
import { addMetadata, updateMetadataFields, deleteMetadataFields } from "@/controllers/API"
import { QuestionTooltip, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip"
import { useTranslation } from "react-i18next"

type MetadataType = "String" | "Number" | "Time"

interface Metadata {
    id: string
    name: string
    type: MetadataType
    createdAt: Date
    updatedAt: Date
}

interface BuiltInMetadata {
    name: string
    type: MetadataType

}

const BUILT_IN_METADATA: BuiltInMetadata[] = [
    { name: "document_id", type: "Number" },
    { name: "document_name", type: "String" },
    { name: "upload_time", type: "Time" },
    { name: "update_time", type: "Time" },
    { name: "uploader", type: "String" },
    { name: "updater", type: "String" },
    { name: "abstract", type: "String" },
    { name: "chunk_index", type: "Number" },
    { name: "bbox", type: "String" },
    { name: "page", type: "Number" },
    { name: "knowledge_id", type: "Number" },
    { name: "user_metadata", type: "String" },
]

const TYPE_ICONS = {
    String: <Type />,
    Number: <Hash />,
    Time: <Clock3 />,
}

const TypeSelector = memo(({
    newType,
    setNewType,
    isSmallScreen
}: {
    newType: MetadataType;
    setNewType: (type: MetadataType) => void;
    isSmallScreen: boolean;
}) => {
    const { t } = useTranslation('knowledge')
    return (
        <div className="space-y-1.5">
            <label className={cname("block font-medium", isSmallScreen ? "text-xs" : "")}>{t('type')}</label>
            <div className="flex gap-1">
                {(["String", "Number", "Time"] as MetadataType[]).map((type) => (
                    <button
                        key={type}
                        onClick={() => setNewType(type)}
                        className={cname(
                            "flex-1 rounded font-medium transition-colors",
                            newType === type
                                ? "bg-blue-600 text-white"
                                : "bg-gray-200 text-gray-700 hover:bg-gray-300",
                            isSmallScreen ? "py-1.5 px-2 text-xs" : "py-2 px-4"
                        )}
                    >
                        {type}
                    </button>
                ))}
            </div>
        </div>
    )
})

interface MetadataManagementDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onSave?: (metadata: Metadata[]) => void;
    hasManagePermission?: boolean;
    id: string;
    initialMetadata?: Array<{ field_name: string; field_type: string; updated_at?: number }>;
}

export function MetadataManagementDialog({
    open,
    onOpenChange,
    onSave,
    hasManagePermission = true,
    id,
    initialMetadata,
}: MetadataManagementDialogProps) {
    const { t } = useTranslation('knowledge')
    const mainDialogRef = useRef<HTMLDivElement>(null)
    const [sideDialogPosition, setSideDialogPosition] = useState({ top: 0, left: 0 })
    const [metadataList, setMetadataList] = useState<Metadata[]>([])
    const [sideDialog, setSideDialog] = useState<{ type: "create" | "rename"; open: boolean }>({
        type: "create",
        open: false
    })
    const [isLoading, setIsLoading] = useState(false)
    const [selectedMetadata, setSelectedMetadata] = useState<Metadata | null>(null)
    const [newName, setNewName] = useState("")
    const [newType, setNewType] = useState<MetadataType>("String")
    const [error, setError] = useState("")
    const [screenWidth, setScreenWidth] = useState(window.innerWidth)
    const isSmallScreen = screenWidth < 1366;
    const sideDialogWidth = isSmallScreen ? 240 : 300;
    const isSideDialogAtRisk = isSmallScreen && sideDialog.open;
    const mainDialogMaxWidth = isSmallScreen ? 600 : 1200;

    const [isSideDialogReady, setIsSideDialogReady] = useState(false);

    useEffect(() => {
        if (open && initialMetadata && initialMetadata.length > 0) {
            const formattedMetadata = initialMetadata.map((item) => ({
                id: `meta_${item.field_name}`,
                name: item.field_name,
                type: (item.field_type.charAt(0).toUpperCase() + item.field_type.slice(1)) as MetadataType,
                createdAt: new Date(),
                updatedAt: item.updated_at ? new Date(item.updated_at * 1000) : new Date(),
            }));
            setMetadataList(formattedMetadata);
        } else if (open) {
            setMetadataList([]);
        }
    }, [open, initialMetadata]);

    const updateSideDialogPosition = useCallback(() => {
        if (mainDialogRef.current) {
            const rect = mainDialogRef.current.getBoundingClientRect();
            const gap = isSmallScreen ? 0 : 4;
            let left = rect.right + gap;
            if (left + sideDialogWidth > screenWidth) left = screenWidth - sideDialogWidth - 8;
            if (sideDialogPosition.left !== left || sideDialogPosition.top !== rect.top) {
                setSideDialogPosition({ top: rect.top, left });
            }
        }
    }, [mainDialogRef, isSmallScreen, screenWidth, sideDialogPosition, sideDialogWidth]);

    useEffect(() => {
        const handleResize = () => {
            const newWidth = window.innerWidth;
            setScreenWidth(newWidth);
        };
        window.addEventListener("resize", handleResize);
        return () => window.removeEventListener("resize", handleResize);
    }, []);

    useEffect(() => {
        if (!open || !sideDialog.open) {
            setIsSideDialogReady(false);
            return;
        }

        // 使用多个阶段的延迟确保位置计算准确
        const timer1 = setTimeout(() => {
            updateSideDialogPosition();
        }, 0);

        const timer2 = setTimeout(() => {
            updateSideDialogPosition();
        }, 50);

        const timer3 = setTimeout(() => {
            updateSideDialogPosition();
            setIsSideDialogReady(true);
        }, 100);

        return () => {
            clearTimeout(timer1);
            clearTimeout(timer2);
            clearTimeout(timer3);
            setIsSideDialogReady(false);
        };
    }, [open, sideDialog.open, updateSideDialogPosition]);

    const validateName = useCallback((name: string): { valid: boolean; error?: string } => {
        const isBuiltInName = BUILT_IN_METADATA.some(meta => meta.name === name);
        if (isBuiltInName) return { valid: false, error: t('builtInNameError') };
        if (!name || name.trim().length === 0) return { valid: false, error: t('nameRequired') };
        if (name.length > 255) return { valid: false, error: t('nameTooLong') };
        if (!/^[a-z][a-z0-9_]*$/.test(name)) return { valid: false, error: t('nameFormatError') };
        const nameExists = metadataList.some((m) => m.name === name && m.id !== selectedMetadata?.id);
        if (nameExists) return { valid: false, error: t('nameExists') };
        return { valid: true };
    }, [metadataList, selectedMetadata, t]);

    const handleCreateClick = useCallback(() => {
        setSideDialog({ type: "create", open: true });
        setNewType("String");
        setNewName("");
        setError("");
        setIsSideDialogReady(false);
    }, []);

    const handleEditClick = useCallback((metadata: Metadata) => {
        setSelectedMetadata(metadata);
        setNewName(metadata.name);
        setSideDialog({ type: "rename", open: true });
        setError("");
        setIsSideDialogReady(false);
    }, []);

    const closeSideDialog = useCallback(() => {
        setSideDialog(prev => ({ ...prev, open: false }));
        setIsSideDialogReady(false);
        setTimeout(() => {
            setSelectedMetadata(null);
            setNewName("");
            setError("");
        }, 300);
    }, []);

    const handleCreateSave = useCallback(async () => {
        if (!id) { setError(t('knowledgeIdMissing')); return; }
        const validation = validateName(newName);
        if (!validation.valid) { setError(validation.error || t('inputInvalid')); return; }

        setIsLoading(true);
        try {
            await addMetadata(id, [{ field_name: newName, field_type: newType.toLowerCase() }]);
            const newMetadata: Metadata = { id: `meta_${newName}`, name: newName, type: newType, createdAt: new Date(), updatedAt: new Date() };
            setMetadataList((prev) => [newMetadata, ...prev]);
            closeSideDialog();
            if (onSave) onSave(metadataList);
        } catch (err: any) {
            setError(err.message || t('createFailed'));
            console.error("创建失败:", err);
        } finally {
            setIsLoading(false);
        }
    }, [newName, newType, id, closeSideDialog, validateName, metadataList, onSave, t]);

    const handleRenameSave = useCallback(async () => {
        if (!id || !selectedMetadata) { setError(t('operationFailed')); return; }
        const validation = validateName(newName);
        if (!validation.valid) { setError(validation.error || t('inputInvalid')); return; }
        if (selectedMetadata.name === newName) { closeSideDialog(); return; }

        setIsLoading(true);
        try {
            await updateMetadataFields(id, [{ old_field_name: selectedMetadata.name, new_field_name: newName }]);
            setMetadataList((prev) => prev.map((m) => m.id === selectedMetadata.id ? { ...m, name: newName, updatedAt: new Date() } : m));
            closeSideDialog();
            if (onSave) onSave(metadataList);
        } catch (err: any) {
            setError(err.message || t('renameFailed'));
            console.error("重命名失败:", err);
        } finally {
            setIsLoading(false);
        }
    }, [newName, selectedMetadata, id, closeSideDialog, validateName, metadataList, onSave, t]);

    const handleDelete = useCallback(async (metadata: Metadata) => {
        if (!id) {
            setError(t('knowledgeIdMissing'));
            return;
        }

        setIsLoading(true);
        try {
            await deleteMetadataFields(id, [metadata.name]);
            setMetadataList((prev) => prev.filter((m) => m.id !== metadata.id));
            if (onSave) onSave(metadataList);
        } catch (err: any) {
            setError(err.message || t('deleteFailed'));
            console.error("删除失败:", err);
        } finally {
            setIsLoading(false);
        }
    }, [id, metadataList, onSave, t]);

    const sortedMetadata = [...metadataList].sort((a, b) => a.updatedAt.getTime() - b.updatedAt.getTime());

    const BubbleConfirm = ({
        trigger,
        onConfirm,
        message = t('confirmDelete')
    }) => {
        const [isOpen, setIsOpen] = useState(false);
        const triggerRef = useRef(null);

        // 点击外部关闭气泡
        useEffect(() => {
            const handleClickOutside = (event) => {
                if (triggerRef.current && !triggerRef.current.contains(event.target)) {
                    setIsOpen(false);
                }
            };

            if (isOpen) {
                document.addEventListener('mousedown', handleClickOutside);
                return () => document.removeEventListener('mousedown', handleClickOutside);
            }
        }, [isOpen]);

        return (
            <div ref={triggerRef} className="relative inline-block">
                <button
                    onClick={() => setIsOpen(!isOpen)}
                    className="p-1.5 hover:bg-gray-200 rounded disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    disabled={trigger.props.disabled}
                >
                    {trigger.props.children}
                </button>

                {isOpen && (
                    <div className="absolute bottom-full left-1/2 mb-2 w-56 bg-white border rounded-lg shadow-lg p-3 z-50"
                        style={{ transform: 'translateX(-84%)' }}>
                        <div className="flex">
                            <CircleQuestionMark size={14} className="text-red-500" />
                            <div className="flex -mt-1 ml-1 font-medium text-sm">{t('tip')}</div>
                        </div>
                        <div className="flex gap-2 mb-3 mt-2">
                            <p className="text-sm ml-10 text-gray-700 font-medium">{message}</p>
                        </div>

                        <div className="flex justify-end gap-2">
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={() => setIsOpen(false)}
                                className="px-2 py-1 h-7 min-h-7 text-xs"
                            >
                                {t('cancel')}
                            </Button>
                            <Button
                                size="sm"
                                onClick={() => {
                                    onConfirm();
                                    setIsOpen(false);
                                }}
                                className="px-2 py-1 h-7 min-h-7 text-xs"
                            >
                                {t('confirm')}
                            </Button>
                        </div>
                        <div className="absolute top-full right-7 -mt-2 w-4 h-4 bg-white border-r border-b transform rotate-45"></div>
                    </div>
                )}
            </div>
        );
    };
    const SideDialogContent = useMemo(() =>
        React.forwardRef<React.ElementRef<typeof DialogPrimitive.Content>, React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>>(
            ({ children, className, ...props }, ref) => (
                <DialogPortal>
                    <DialogPrimitive.Content
                        ref={ref}
                        {...props}
                        className={cname(
                            "fixed z-50 grid gap-4 border bg-background dark:bg-[#303134] shadow-lg sm:rounded-lg",
                            `w-[${sideDialogWidth}px]`,
                            isSmallScreen ? "p-3 text-sm" : "p-5",
                            className
                        )}
                        style={{
                            top: `${sideDialogPosition.top}px`,
                            left: `${sideDialogPosition.left}px`,
                            transform: "none",
                            maxHeight: "80vh",
                            // 只有在位置计算完成后才显示
                            opacity: isSideDialogReady ? 1 : 0,
                            transition: 'opacity 0.05s ease-in-out'
                        }}
                    >
                        {children}
                        <DialogPrimitive.Close className="absolute right-3 top-3 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none data-[state=open]:bg-accent data-[state=open]:text-muted-foreground">
                            <X className={isSmallScreen ? "h-3 w-3" : "h-4 w-4"} />
                            <span className="sr-only">Close</span>
                        </DialogPrimitive.Close>
                    </DialogPrimitive.Content>
                </DialogPortal>
            )
        )
        , [sideDialogWidth, isSmallScreen, sideDialogPosition, isSideDialogReady]);
    SideDialogContent.displayName = "SideDialogContent";

    return (
        <>
            <Dialog open={open} onOpenChange={onOpenChange}>
                <DialogContent
                    ref={mainDialogRef}
                    className={cname("max-h-[70vh] overflow-y-auto", typeof mainDialogMaxWidth === "string" ? "" : `w-[${mainDialogMaxWidth}px]`)}
                    style={{
                        width: mainDialogMaxWidth, maxWidth: "none",
                        left: isSideDialogAtRisk ? "8px" : isSmallScreen ? "calc(50% - 300px)" : "calc(50% - 600px)",
                        top: "50%", transform: "translateY(-50%)", minWidth: 580
                    }}
                >
                    <DialogHeader>
                        <DialogTitle className={isSmallScreen ? "text-base" : ""}>{t('metaData')}</DialogTitle>
                    </DialogHeader>
                    <div className="meta-dialog space-y-6">
                        <button
                            onClick={handleCreateClick} disabled={!hasManagePermission}
                            className={cname("w-full flex items-center justify-center gap-2 rounded-lg bg-muted hover:bg-accent disabled:opacity-50 disabled:cursor-not-allowed transition-colors", isSmallScreen ? "py-2" : "py-3")}
                        >
                            <Plus size={isSmallScreen ? 16 : 20} />
                            <span>{t('createMetadata')}</span>
                        </button>

                        <div className="space-y-2">
                            {sortedMetadata.map((metadata) => (
                                <div
                                    key={metadata.id}
                                    className={cname("flex items-center justify-between rounded-lg bg-muted hover:bg-accent transition-colors", isSmallScreen ? "p-2 gap-2" : "p-3 gap-3")}
                                >
                                    <div className="flex items-center gap-2 flex-1">
                                        <span className={isSmallScreen ? "text-base" : "text-lg"}>{TYPE_ICONS[metadata.type]}</span>
                                        <span className={cname("text-gray-500", isSmallScreen ? "text-xs" : "text-sm")}>{metadata.type}</span>
                                        <div className=" min-w-0 max-w-64">
                                            <TooltipProvider>
                                                <Tooltip>
                                                    <TooltipTrigger asChild>
                                                        <span
                                                            className={cname(
                                                                "font-medium truncate block",
                                                                isSmallScreen ? "text-sm" : "",
                                                                "max-w-full" // 确保它不会超出父容器
                                                            )}
                                                            style={{
                                                                whiteSpace: 'nowrap',
                                                                overflow: 'hidden',
                                                                textOverflow: 'ellipsis',
                                                                width: '100%'
                                                            }}
                                                        >
                                                            {metadata.name}
                                                        </span>
                                                    </TooltipTrigger>
                                                    <TooltipContent className="max-w-[200px] whitespace-normal"
                                                        style={{
                                                            whiteSpace: 'normal',
                                                            wordBreak: 'break-word'
                                                        }}
                                                    >
                                                        <p>{metadata.name}</p>
                                                    </TooltipContent>
                                                </Tooltip>
                                            </TooltipProvider>
                                        </div>
                                    </div>
                                    <div className="flex gap-1">
                                        <button
                                            onClick={() => handleEditClick(metadata)} disabled={!hasManagePermission || isLoading}
                                            className="p-1.5 hover:bg-gray-200 rounded disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                                        >
                                            <SquarePen size={isSmallScreen ? 16 : 18} />
                                        </button>
                                        <BubbleConfirm
                                            trigger={
                                                <button disabled={!hasManagePermission || isLoading}>
                                                    <Trash2 size={isSmallScreen ? 16 : 18} />
                                                </button>
                                            }
                                            message={t('confirmDeleteMetadata')}
                                            onConfirm={() => handleDelete(metadata)}
                                        />
                                    </div>
                                </div>
                            ))}
                        </div>

                        <div className="space-y-3">
                            <div className="flex items-center gap-2">
                                <h3 className={cname("font-semibold", isSmallScreen ? "text-sm" : "")}>{t('builtInMetadata')}</h3>
                                <div className="group relative">
                                    <QuestionTooltip className="relative top-0.5 ml-1" content={t('builtInMetadataTooltip')}></QuestionTooltip>
                                </div>
                            </div>
                            <div className="space-y-2">
                                {BUILT_IN_METADATA.slice(0, 6).map((metadata) => (
                                    <div
                                        key={metadata.name}
                                        className={cname("flex items-center bg-muted rounded-lg", isSmallScreen ? "p-2 gap-2" : "p-3 gap-3")}
                                    >
                                        <span className={isSmallScreen ? "text-base" : "text-lg"}>{TYPE_ICONS[metadata.type]}</span>
                                        <span className={cname("text-gray-500", isSmallScreen ? "text-xs" : "text-sm")}>{metadata.type}</span>
                                        <span className={cname("font-medium truncate", isSmallScreen ? "text-sm" : "")}>{metadata.name}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                </DialogContent>
            </Dialog>

            <Dialog key="metadata-side-dialog" open={sideDialog.open} onOpenChange={closeSideDialog}>
                <SideDialogContent className="overflow-y-auto">
                    {sideDialog.type === "create" && (
                        <>
                            <DialogHeader>
                                <DialogTitle className={isSmallScreen ? "text-base" : ""}>{t('createMetadata')}</DialogTitle>
                                <DialogDescription className={isSmallScreen ? "text-xs" : ""}>{t('createMetadataDescription')}</DialogDescription>
                            </DialogHeader>
                            <div className="space-y-3">
                                <TypeSelector newType={newType} setNewType={setNewType} isSmallScreen={isSmallScreen} />
                                <div className="space-y-1.5">
                                    <label className={cname("block font-medium", isSmallScreen ? "text-xs" : "")}>{t('metadatainfor.name')}</label>
                                    <Input
                                        id="create-metadata-name" value={newName} onChange={(e) => { setNewName(e.target.value); if (error) setError(""); }}
                                        placeholder={t('pleaseEnter')} autoComplete="off" autoFocus
                                        className={cname(error ? "border-red-500 border-2" : "", isSmallScreen ? "text-sm h-8" : "")}
                                    />
                                    {error && (
                                        <div className={cname("flex items-center gap-1.5 text-red-500", isSmallScreen ? "text-xs" : "text-sm")}>
                                            <span>{error}</span>
                                        </div>
                                    )}
                                </div>
                                <div className={cname("flex justify-end gap-2 pt-2", isSmallScreen ? "" : "pt-4 gap-3")}>
                                    <Button variant="outline" onClick={closeSideDialog} className={isSmallScreen ? "px-3 py-1 text-xs" : ""}>{t('cancel')}</Button>
                                    <Button onClick={handleCreateSave} disabled={isLoading} className={cname("bg-blue-600 hover:bg-blue-700", isSmallScreen ? "px-3 py-1 text-xs" : "")}>
                                        {isLoading ? t('saving') : t('save')}
                                    </Button>
                                </div>
                            </div>
                        </>
                    )}
                    {sideDialog.type === "rename" && (
                        <>
                            <DialogHeader>
                                <DialogTitle className={isSmallScreen ? "text-base" : ""}>{t('rename')}</DialogTitle>
                                <DialogDescription className={isSmallScreen ? "text-xs" : ""}>{t('renameDescription')}</DialogDescription>
                            </DialogHeader>
                            <div className="space-y-3">
                                <div className="space-y-1.5">
                                    <label className={cname("block font-medium", isSmallScreen ? "text-xs" : "")}>{t('name')}</label>
                                    <Input
                                        id="rename-metadata-name" value={newName} onChange={(e) => { setNewName(e.target.value); if (error) setError(""); }}
                                        placeholder={t('pleaseEnter')} autoComplete="off" autoFocus
                                        className={cname(error ? "border-red-500 border-2" : "", isSmallScreen ? "text-sm h-8" : "")}
                                    />
                                    {error && (
                                        <div className={cname("flex items-center gap-1.5 text-red-500", isSmallScreen ? "text-xs" : "text-sm")}>
                                            <span>{error}</span>
                                        </div>
                                    )}
                                </div>
                                <div className={cname("flex justify-end gap-2 pt-2", isSmallScreen ? "" : "pt-4 gap-3")}>
                                    <Button variant="outline" onClick={closeSideDialog} className={isSmallScreen ? "px-3 py-1 text-xs" : ""}>{t('cancel')}</Button>
                                    <Button onClick={handleRenameSave} disabled={isLoading} className={cname("bg-blue-600 hover:bg-blue-700", isSmallScreen ? "px-3 py-1 text-xs" : "")}>
                                        {isLoading ? t('saving') : t('save')}
                                    </Button>
                                </div>
                            </div>
                        </>
                    )}
                </SideDialogContent>
            </Dialog>
        </>
    )
}