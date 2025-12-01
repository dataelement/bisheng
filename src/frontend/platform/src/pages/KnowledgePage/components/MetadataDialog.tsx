import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogDescription } from '@/components/bs-ui/dialog';
import { Button } from '@/components/bs-ui/button';
import { Plus, Search, Trash2, Type, Hash, Clock3, X } from 'lucide-react';
import { cname } from "@/components/bs-ui/utils";
import { toast } from "@/components/bs-ui/toast/use-toast";
import { format } from "date-fns";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { DatePicker } from "@/components/bs-ui/calendar/datePicker";
import * as DialogPrimitive from "@radix-ui/react-dialog";

// Types
interface MetadataItem {
    id: string;
    name: string;
    type: 'String' | 'Number' | 'Time';
    value?: string;
    description?: string;
    updated?: number;
    updated_at?: string;
}

interface FileInfo {
    id?: string;
    file_name?: string;
    create_time?: string;
    update_time?: string;
    creat_user?: string;
    update_user?: string;
    file_size?: number;
    split_rule?: string;
    title?: string;
    user_metadata?: Record<string, any>;
}

interface MetadataDialogProps {
    open: boolean;
    file: FileInfo | null;
}

interface SideDialogProps {
    type: 'search' | 'create' | null;
    open: boolean;
}

interface NewMetadata {
    name: string;
    type: 'String' | 'Number' | 'Time';
}

// Type icon constants
const TYPE_ICONS = {
    String: <Type />,
    Number: <Hash />,
    Time: <Clock3 />
};

// Metadata row component
export const MetadataRow = React.memo(({
    isKnowledgeAdmin,
    item,
    onDelete,
    onValueChange,
    isSmallScreen,
    t,
    showInput = true
}: {
    isKnowledgeAdmin: boolean;
    item: MetadataItem;
    onDelete: (id: string) => void;
    onValueChange: (id: string, value: string) => void;
    isSmallScreen: boolean;
    t: (key: string) => string;
    showInput?: boolean;
}) => {
    console.log(item);

    const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        onValueChange(item.id, e.target.value);
    };

    const handleNumberChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const value = e.target.value;
        if (value === '' || /^-?\d*\.?\d*$/.test(value)) {
            onValueChange(item.id, value);
        }
    };

    return (
        <div className="flex items-center gap-3 p-2 w-full">
            <div className="flex items-center gap-2 flex-1 p-2 rounded-lg bg-gray-50 h-11 min-w-[180px]">
                <span className={isSmallScreen ? "text-base" : "text-lg"}>
                    {TYPE_ICONS[item.type]}
                </span>
                <span className={cname(
                    "text-gray-500 min-w-[60px]",
                    isSmallScreen ? "text-xs" : "text-sm"
                )}>
                    {item.type}
                </span>
                <div className="min-w-0 flex-1 max-w-[120px]">
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <span
                                    className={cname(
                                        "font-medium truncate block",
                                        isSmallScreen ? "text-sm" : "",
                                        "max-w-full"
                                    )}
                                    style={{
                                        whiteSpace: 'nowrap',
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                    }}
                                >
                                    {item.name}
                                </span>
                            </TooltipTrigger>
                            <TooltipContent className="max-w-[200px] whitespace-normal"
                                style={{
                                    whiteSpace: 'normal',
                                    wordBreak: 'break-word'
                                }}
                            >
                                <p>{item.name}</p>
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                </div>
            </div>
            <div className="flex items-center gap-2 flex-2 justify-end p-2 rounded-lg bg-gray-50 h-11 ml-10 min-w-[180px]">
                {showInput && (
                    <div className="w-40">
                        {item.type === 'String' && (
                            <input
                                disabled={!isKnowledgeAdmin}
                                type="text"
                                value={item.value || ''}
                                onChange={handleInputChange}
                                maxLength={255}
                                placeholder={t('metadatainfor.enterText')}
                                className={cname(
                                    "w-full px-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                                    isSmallScreen ? "py-0.5 text-xs h-6" : "py-1 text-sm h-7"
                                )}
                            />
                        )}

                        {item.type === 'Number' && (
                            <input
                                disabled={!isKnowledgeAdmin}
                                type="number"
                                value={item.value === '' || item.value === null || item.value === undefined ? 0 : item.value}
                                onChange={handleNumberChange}
                                onBlur={(e: React.FocusEvent<HTMLInputElement>) => {
                                    // When losing focus, if value is empty string, set to 0
                                    if (e.target.value === '') {
                                        onValueChange(item.id, '0');
                                    }
                                }}
                                className={cname(
                                    "w-full px-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                                    isSmallScreen ? "py-0.5 text-xs h-6" : "py-1 text-sm h-7"
                                )}
                            />
                        )}

                        {item.type === 'Time' && (
                            <DatePicker
                                disabled={!isKnowledgeAdmin}
                                value={item.value ? new Date(item.value) : undefined}
                                placeholder={t('metadatainfor.selectTime')}
                                showTime={true}
                                onChange={(selectedDate: Date | undefined) => {
                                    const formattedValue = selectedDate
                                        ? format(selectedDate, 'yyyy-MM-dd HH:mm:ss')
                                        : '';
                                    onValueChange(item.id, formattedValue);
                                }}
                            />
                        )}
                    </div>
                )}
            </div>

            <button
                onClick={() => onDelete(item.id)}
                disabled={!isKnowledgeAdmin}
                className="p-1 rounded transition-colors flex-shrink-0 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                title={t('metacommon.delete')}
            >
                <Trash2 size={isSmallScreen ? 18 : 20} className="text-gray-500" />
            </button>
        </div>
    )
});

MetadataRow.displayName = 'MetadataRow';

// Main metadata dialog component
export const MainMetadataDialog = React.memo(({
    metadataDialog,
    setMetadataDialog,
    mainMetadataList,
    fileInfor,
    isKnowledgeAdmin,
    isSmallScreen,
    t,
    formatFileSize,
    splitRuleDesc,
    handleSaveUserMetadata,
    handleSearchMetadataClick,
    handleDeleteMainMetadata,
    handleMainMetadataValueChange,
    mainMetadataDialogRef
}: {
    metadataDialog: MetadataDialogProps;
    setMetadataDialog: (dialog: MetadataDialogProps) => void;
    mainMetadataList: MetadataItem[];
    fileInfor: FileInfo | undefined;
    isKnowledgeAdmin: boolean;
    isSmallScreen: boolean;
    t: (key: string) => string;
    formatFileSize: (bytes: number) => string;
    splitRuleDesc: (file: FileInfo) => string;
    handleSaveUserMetadata: () => void;
    handleSearchMetadataClick: () => void;
    handleDeleteMainMetadata: (id: string) => void;
    handleMainMetadataValueChange: (id: string, value: string) => void;
    mainMetadataDialogRef: React.RefObject<HTMLDivElement>;
}) => {
    return (
        <Dialog open={metadataDialog.open} onOpenChange={(open) => setMetadataDialog({ ...metadataDialog, open })}>
            <DialogContent
                ref={mainMetadataDialogRef}
                className="sm:max-w-[525px] max-w-[625px] h-[80vh] flex flex-col"
                style={{
                    transition: 'none'
                }}
            >
                <DialogHeader>
                    <h3 className="text-lg font-semibold">{t('metadatainfor.title')}</h3>
                </DialogHeader>

                <div className="flex-1 overflow-y-auto min-h-0">
                    <button
                        onClick={handleSearchMetadataClick}
                        disabled={!isKnowledgeAdmin}
                        className="py-2 w-full flex items-center justify-center gap-2 rounded-lg bg-gray-100 hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors mb-4"
                    >
                        <Plus size={16} />
                        <span>{t('metadatainfor.addMetadata')}</span>
                    </button>

                    {mainMetadataList.length > 0 && (
                        <div className="space-y-2">
                            {mainMetadataList.map((metadata) => (
                                <MetadataRow
                                    isKnowledgeAdmin={isKnowledgeAdmin}
                                    key={metadata.id}
                                    item={metadata}
                                    onDelete={handleDeleteMainMetadata}
                                    onValueChange={handleMainMetadataValueChange}
                                    isSmallScreen={isSmallScreen}
                                    t={t}
                                    showInput={true}
                                />
                            ))}
                        </div>
                    )}

                    <div className="grid gap-4 py-4">
                        <div className="font-medium">{t('fileinfor.documentInfo')}</div>
                        {fileInfor && <div className="space-y-2">
                            {[
                                {
                                    label: t('fileinfor.fileId'),
                                    value: fileInfor?.id,
                                },
                                {
                                    label: t('fileinfor.fileName'),
                                    value: fileInfor?.file_name,
                                    isFileName: true
                                },
                                {
                                    label: t('fileinfor.createTime'),
                                    value: fileInfor?.create_time ? metadataDialog.file?.create_time?.replace('T', ' ') : null
                                },
                                {
                                    label: t('fileinfor.updateTime'),
                                    value: fileInfor?.update_time ? fileInfor?.update_time.replace('T', ' ') : null
                                },
                                {
                                    label: t('fileinfor.creator'),
                                    value: fileInfor?.creat_user,
                                },
                                {
                                    label: t('fileinfor.updater'),
                                    value: fileInfor?.update_user,
                                },
                                {
                                    label: t('fileinfor.originalFileSize'),
                                    value: fileInfor?.file_size ? formatFileSize(metadataDialog.file?.file_size || 0) : null
                                },
                                {
                                    label: t('fileinfor.splitStrategy'),
                                    value: fileInfor ? splitRuleDesc(fileInfor) : null
                                },
                                {
                                    label: t('fileinfor.fullTextSummary'),
                                    value: metadataDialog.file?.title
                                }
                            ].map((item, index) => (
                                item.value && (
                                    <div key={index} className="grid grid-cols-4 gap-4 items-center">
                                        <span className="text-sm text-muted-foreground col-span-1">{item.label}</span>
                                        <span className={`col-span-3 text-sm ${item.isFileName ? 'truncate max-w-full' : ''}`}>
                                            {item.value || t('metacommon.none')}
                                        </span>
                                    </div>
                                )
                            ))}
                        </div>}
                    </div>
                </div>

                <div className="flex justify-end gap-2 pt-4 border-t border-gray-200 flex-shrink-0">
                    <Button
                        variant="outline"
                        onClick={() => setMetadataDialog({ ...metadataDialog, open: false })}
                        className={cname(isSmallScreen ? "px-3 py-1 text-xs" : "px-4 py-2 text-sm")}
                    >
                        {t('metacommon.cancel')}
                    </Button>
                    <Button
                        onClick={handleSaveUserMetadata}
                        disabled={!isKnowledgeAdmin}
                        className={cname(
                            "bg-blue-500 hover:bg-blue-600",
                            isSmallScreen ? "px-3 py-1 text-xs" : "px-4 py-2 text-sm"
                        )}
                    >
                        {t('metacommon.save')}
                    </Button>
                </div>
            </DialogContent>
        </Dialog>
    );
});

MainMetadataDialog.displayName = 'MainMetadataDialog';

// Right sidebar dialog component
export const MetadataSideDialog = React.memo(({
    sideDialog,
    closeSideDialog,
    predefinedMetadata,
    searchTerm,
    setSearchTerm,
    newMetadata,
    setNewMetadata,
    metadataError,
    setMetadataError,
    isKnowledgeAdmin,
    isSmallScreen,
    t,
    sideDialogWidth,
    sideDialogPosition,
    isSideDialogPositioned,
    handleAddFromSearch,
    handleCreateMetadataClick,
    handleSaveNewMetadata,
    setSideDialog
}: {
    sideDialog: SideDialogProps;
    closeSideDialog: () => void;
    predefinedMetadata: MetadataItem[];
    searchTerm: string;
    setSearchTerm: (term: string) => void;
    newMetadata: NewMetadata;
    setNewMetadata: (metadata: NewMetadata) => void;
    metadataError: string;
    setMetadataError: (error: string) => void;
    isKnowledgeAdmin: boolean;
    isSmallScreen: boolean;
    t: (key: string) => string;
    sideDialogWidth: number;
    sideDialogPosition: { top: number; left: number };
    isSideDialogPositioned: boolean;
    handleAddFromSearch: (metadata: MetadataItem) => void;
    handleCreateMetadataClick: () => void;
    handleSaveNewMetadata: () => void;
    setSideDialog: (dialog: SideDialogProps) => void;
}) => {
    const searchInputRef = useRef<HTMLInputElement>(null);

    const filteredPredefinedMetadata = useMemo(() => {
        return predefinedMetadata
            .filter(meta =>
                meta.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
                (meta.description && meta.description.toLowerCase().includes(searchTerm.toLowerCase()))
            )
            .sort((a, b) => {
                const updatedA = a.updated || 0;
                const updatedB = b.updated || 0;
                return updatedA - updatedB;
            });
    }, [predefinedMetadata, searchTerm]);

    const SideDialogContent = useMemo(() =>
        React.forwardRef<HTMLDivElement, React.ComponentProps<typeof DialogPrimitive.Content>>(
            ({ children, className, ...props }, ref) => (
                <DialogPrimitive.Portal>
                    <DialogPrimitive.Content
                        ref={ref}
                        {...props}
                        className={cname(
                            "fixed z-50 flex flex-col border bg-background dark:bg-[#303134] shadow-lg sm:rounded-lg",
                            `w-[${sideDialogWidth}px]`,
                            isSmallScreen ? "p-3 text-sm" : "p-5",
                            className
                        )}
                        style={{
                            top: `${sideDialogPosition.top}px`,
                            left: `${sideDialogPosition.left}px`,
                            transform: "none",
                            maxHeight: "80vh",
                            opacity: isSideDialogPositioned ? 1 : 0,
                            transition: 'opacity 0.05s ease-in-out'
                        }}
                    >
                        {children}
                        <DialogPrimitive.Close
                            className="absolute right-3 top-3 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none data-[state=open]:bg-accent data-[state=open]:text-muted-foreground"
                            onClick={closeSideDialog}
                        >
                            <X className={isSmallScreen ? "h-3 w-3" : "h-4 w-4"} />
                            <span className="sr-only">Close</span>
                        </DialogPrimitive.Close>
                    </DialogPrimitive.Content>
                </DialogPrimitive.Portal>
            )
        ), [sideDialogWidth, isSmallScreen, sideDialogPosition, isSideDialogPositioned, closeSideDialog]);

    SideDialogContent.displayName = "SideDialogContent";

    return (
        <DialogPrimitive.Dialog open={sideDialog.open} onOpenChange={(open) => {
            if (!open) closeSideDialog();
        }}>
            <SideDialogContent>
                {sideDialog.type === 'search' && (
                    <>
                        <DialogHeader>
                            <div className="relative w-full">
                                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-blue-500" />
                                <input
                                    ref={searchInputRef}
                                    type="text"
                                    placeholder={t('metadatainfor.searchMetadata')}
                                    className={cname(
                                        "w-full pl-9 pr-3 py-2 text-sm bg-white rounded-md outline-none ring-1 ring-gray-200",
                                        isSmallScreen ? "text-xs py-1.5" : ""
                                    )}
                                    value={searchTerm}
                                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                                        e.stopPropagation();
                                        setSearchTerm(e.target.value);
                                    }}
                                    onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => {
                                        e.stopPropagation();
                                        if (e.key === 'Escape') {
                                            closeSideDialog();
                                        }
                                    }}
                                    onClick={(e: React.MouseEvent<HTMLInputElement>) => {
                                        e.stopPropagation();
                                    }}
                                />
                            </div>
                        </DialogHeader>

                        <div className="flex-1 min-h-0 mt-2 mb-2 overflow-y-auto">
                            <div
                                className="h-full overflow-y-auto"
                                onWheel={(e: React.WheelEvent<HTMLDivElement>) => {
                                    e.stopPropagation();
                                }}
                            >
                                <div className="space-y-3 pr-2">
                                    {filteredPredefinedMetadata.map((metadata) => (
                                        <div
                                            key={metadata.id}
                                            className="flex items-center justify-between p-3 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors cursor-pointer"
                                            onClick={() => handleAddFromSearch(metadata)}
                                        >
                                            <div className="flex items-center gap-3 flex-1 min-w-0">
                                                <span className={isSmallScreen ? "text-base" : "text-lg"}>
                                                    {TYPE_ICONS[metadata.type]}
                                                </span>
                                                <span className={cname(
                                                    "text-gray-500 min-w-[60px]",
                                                    isSmallScreen ? "text-xs" : "text-sm"
                                                )}>
                                                    {metadata.type}
                                                </span>

                                                <TooltipProvider>
                                                    <Tooltip>
                                                        <TooltipTrigger asChild>
                                                            <div className="flex-1 min-w-0">
                                                                <div className="font-medium text-sm truncate">
                                                                    {metadata.name}
                                                                </div>
                                                            </div>
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
                                    ))}
                                </div>
                            </div>
                        </div>

                        <div className="grid gap-4 pt-4 border-t">
                            <div className="space-y-2">
                                <button
                                    onClick={handleCreateMetadataClick}
                                    disabled={!isKnowledgeAdmin}
                                    className="py-2 w-full flex items-center justify-center gap-2 rounded-lg bg-gray-100 hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                                >
                                    <Plus size={isSmallScreen ? 14 : 16} />
                                    <span>{t('metadatainfor.createMetadata')}</span>
                                </button>
                            </div>
                        </div>
                    </>
                )}

                {sideDialog.type === 'create' && (
                    <>
                        <DialogHeader>
                            <h3 className={cname("text-lg font-semibold", isSmallScreen ? "text-base" : "")}>{t('metadatainfor.createMetadata')}</h3>
                            <DialogDescription className={isSmallScreen ? "text-xs" : ""}>
                                {t('metadatainfor.enterNewMetadataInfo')}
                            </DialogDescription>
                        </DialogHeader>

                        <div className="grid gap-4 py-4">
                            <div className="space-y-1.5">
                                <label className={cname("block font-medium", isSmallScreen ? "text-xs" : "")}>{t('metadatainfor.type')}</label>
                                <div className="flex gap-1">
                                    {(['String', 'Number', 'Time'] as const).map((type) => (
                                        <button
                                            key={type}
                                            onClick={() => setNewMetadata(prev => ({ ...prev, type }))}
                                            className={cname(
                                                "flex-1 rounded-md font-medium transition-colors",
                                                newMetadata.type === type
                                                    ? "bg-blue-500 text-white"
                                                    : "bg-gray-100 hover:bg-gray-200 text-gray-700",
                                                isSmallScreen ? "py-1.5 px-2 text-xs" : "py-2 px-4 text-sm"
                                            )}
                                        >
                                            {type}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            <div className="space-y-1.5">
                                <label className={cname("block font-medium", isSmallScreen ? "text-xs" : "")}>{t('metadatainfor.name')}</label>
                                <input
                                    type="text"
                                    value={newMetadata.name}
                                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                                        setNewMetadata(prev => ({ ...prev, name: e.target.value }));
                                        if (metadataError) setMetadataError('');
                                    }}
                                    placeholder={t('metadatainfor.enterMetadataName')}
                                    className={cname(
                                        "w-full px-3 py-2 border rounded-md text-sm",
                                        isSmallScreen ? "text-xs h-8 py-1.5" : "",
                                        metadataError ? "border-red-500 focus:ring-red-500" : "border-gray-300 focus:ring-blue-500"
                                    )}
                                />
                            </div>

                            {metadataError && (
                                <div className={cname(
                                    "flex items-center gap-1.5 text-red-500",
                                    isSmallScreen ? "text-xs" : "text-sm"
                                )}>
                                    <span>{metadataError}</span>
                                </div>
                            )}
                        </div>

                        <div className="flex justify-end gap-2">
                            <Button
                                variant="outline"
                                onClick={() => setSideDialog({ type: 'search', open: true })}
                                className={cname(isSmallScreen ? "px-3 py-1 text-xs" : "px-4 py-2 text-sm")}
                            >
                                {t('metacommon.cancel')}
                            </Button>
                            <Button
                                onClick={handleSaveNewMetadata}
                                className={cname(
                                    "bg-blue-500 hover:bg-blue-600",
                                    isSmallScreen ? "px-3 py-1 text-xs" : "px-4 py-2 text-sm"
                                )}
                            >
                                {t('metacommon.save')}
                            </Button>
                        </div>
                    </>
                )}
            </SideDialogContent>
        </DialogPrimitive.Dialog>
    );
});

MetadataSideDialog.displayName = 'MetadataSideDialog';