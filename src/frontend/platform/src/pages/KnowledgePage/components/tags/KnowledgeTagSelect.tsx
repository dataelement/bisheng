import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/bs-ui/dialog";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import {
    batchAddFileTagsApi,
    createKnowledgeTagApi,
    deleteKnowledgeTagApi,
    getKnowledgeTagsApi,
    KnowledgeTagItem,
    setFileTagsApi
} from "@/controllers/API/knowledgeTags";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { truncateString } from "@/util/utils";
import { Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

interface KnowledgeTagSelectProps {
    knowledgeId: string | number;
    fileIds: number[];
    initialTags?: KnowledgeTagItem[];
    children: React.ReactNode;
    onUpdate: () => void;
    isEditable?: boolean;
}

const TAG_NAME_MAX_LENGTH = 100;
const TAG_DISPLAY_MAX_LENGTH = 18;

export default function KnowledgeTagSelect({
    knowledgeId,
    fileIds,
    initialTags = [],
    children,
    onUpdate,
    isEditable = true
}: KnowledgeTagSelectProps) {
    const { toast } = useToast();
    const { t } = useTranslation('knowledge');
    const [open, setOpen] = useState(false);
    const [tags, setTags] = useState<KnowledgeTagItem[]>([]);
    const [selectedTagIds, setSelectedTagIds] = useState<number[]>([]);
    const [inputValue, setInputValue] = useState("");
    const [loading, setLoading] = useState(false);
    const [deletingTagId, setDeletingTagId] = useState<number | null>(null);

    const isBatch = fileIds.length > 1;
    const numericKnowledgeId = Number(knowledgeId);

    const syncSelectedTags = () => {
        if (isBatch) {
            setSelectedTagIds([]);
            return;
        }
        setSelectedTagIds(initialTags.map(tag => tag.id));
    };

    const fetchTags = async () => {
        if (!numericKnowledgeId) return;
        const response = await captureAndAlertRequestErrorHoc(
            getKnowledgeTagsApi(numericKnowledgeId, {
                page: 1,
                limit: 100
            })
        );

        if (!response || response === 'canceled') {
            return;
        }

        setTags(response.data ?? []);
    };

    useEffect(() => {
        if (!open) return;
        setInputValue("");
        syncSelectedTags();
        fetchTags();
    }, [open, numericKnowledgeId]);

    useEffect(() => {
        if (!open || isBatch) return;
        setSelectedTagIds(initialTags.map(tag => tag.id));
    }, [initialTags, isBatch, open]);

    useEffect(() => {
        document.body.dataset.knowledgeTagDialogOpen = open ? 'true' : 'false';

        return () => {
            document.body.dataset.knowledgeTagDialogOpen = 'false';
        };
    }, [open]);

    const handleOpenChange = (nextOpen: boolean) => {
        setOpen(nextOpen);
        if (!nextOpen) {
            setInputValue("");
            syncSelectedTags();
        }
    };

    const validateTagName = (value: string) => {
        const name = value.trim();
        if (!name) return false;
        if (name.length > TAG_NAME_MAX_LENGTH) {
            toast({ variant: 'error', description: t('tagNameMaxLength', { count: TAG_NAME_MAX_LENGTH }) });
            return false;
        }
        return true;
    };

    const toggleTag = (tagId: number) => {
        const nextIds = selectedTagIds.includes(tagId)
            ? selectedTagIds.filter(id => id !== tagId)
            : [...selectedTagIds, tagId];

        setSelectedTagIds(nextIds);
    };

    const handleCreateTag = async (tagName: string) => {
        if (!validateTagName(tagName)) return;

        const existing = tags.find((tag) => tag.name.trim().toLowerCase() === tagName.trim().toLowerCase());
        if (existing) {
            if (!selectedTagIds.includes(existing.id)) {
                setSelectedTagIds((prev) => [...prev, existing.id]);
            }
            setInputValue("");
            return;
        }

        const result = await captureAndAlertRequestErrorHoc(
            createKnowledgeTagApi(numericKnowledgeId, tagName)
        );

        if (!result || result === 'canceled') {
            return;
        }

        const newTag = result as KnowledgeTagItem;
        setTags(prev => [newTag, ...prev.filter(tag => tag.id !== newTag.id)]);
        setSelectedTagIds((prev) => (prev.includes(newTag.id) ? prev : [...prev, newTag.id]));
        setInputValue("");
    };

    const handleDeleteTag = async (tag: KnowledgeTagItem) => {
        if (deletingTagId !== null) return;
        setDeletingTagId(tag.id);
        const result = await captureAndAlertRequestErrorHoc(deleteKnowledgeTagApi(numericKnowledgeId, tag.id));
        if (result === false || result === 'canceled') {
            setDeletingTagId(null);
            return;
        }
        setTags(prev => prev.filter(item => item.id !== tag.id));
        setSelectedTagIds(prev => prev.filter(id => id !== tag.id));
        toast({ variant: 'success', description: t('tagDeleted') });
        setDeletingTagId(null);
    };

    const selectedTags = useMemo(
        () => tags.filter(tag => selectedTagIds.includes(tag.id)),
        [tags, selectedTagIds]
    );

    const handleSave = async () => {
        setLoading(true);
        const payloadTagIds = [...selectedTagIds];
        const result = await captureAndAlertRequestErrorHoc(
            isBatch
                ? batchAddFileTagsApi({
                    knowledge_id: numericKnowledgeId,
                    file_ids: fileIds,
                    tag_ids: payloadTagIds
                })
                : setFileTagsApi({
                    knowledge_id: numericKnowledgeId,
                    file_id: fileIds[0],
                    tag_ids: payloadTagIds
                })
        );
        setLoading(false);
        if (result === false || result === 'canceled') {
            return;
        }
        onUpdate();
        handleOpenChange(false);
    };

    return (
        <Dialog open={open} onOpenChange={handleOpenChange}>
            <DialogTrigger asChild>{children}</DialogTrigger>
            <DialogContent
                close={false}
                className="w-[600px] max-w-[calc(100vw-32px)] gap-0 rounded-xl border-none p-0"
                onClick={(event) => event.stopPropagation()}
            >
                <DialogHeader className="px-6 py-4">
                    <DialogTitle className="text-[16px] font-medium leading-6 text-[#212121]">
                        编辑标签
                    </DialogTitle>
                </DialogHeader>
                <div className="flex flex-col gap-4 px-6 pb-3">
                    <div
                        className="relative flex min-h-8 cursor-text flex-wrap items-center gap-1 rounded-[8px] border border-[#EBECF0] bg-white px-3 py-[5px] pr-[40px] transition-colors focus-within:border-primary"
                        onClick={(event) => {
                            const target = event.currentTarget.querySelector("input") as HTMLInputElement | null;
                            target?.focus();
                        }}
                    >
                        {selectedTags.map((tag) => (
                            <span
                                key={tag.id}
                                className="flex h-[22px] items-center justify-center gap-1 whitespace-nowrap rounded-[4px] bg-[#f2f3f5] px-2 text-sm leading-[22px] text-[#4e5969]"
                            >
                                <span className="max-w-[180px] truncate" title={tag.name}>
                                    {truncateString(tag.name, TAG_DISPLAY_MAX_LENGTH)}
                                </span>
                                <button
                                    type="button"
                                    className="flex h-4 w-4 items-center justify-center text-[#86909c] hover:text-[#4e5969]"
                                    onClick={(event) => {
                                        event.stopPropagation();
                                        toggleTag(tag.id);
                                    }}
                                >
                                    <X className="h-3.5 w-3.5" />
                                </button>
                            </span>
                        ))}
                        <input
                            type="text"
                            value={inputValue}
                            maxLength={TAG_NAME_MAX_LENGTH}
                            onChange={(event) => setInputValue(event.target.value)}
                            onKeyDown={(event) => {
                                if (event.key === "Enter") {
                                    event.preventDefault();
                                    void handleCreateTag(inputValue.trim());
                                }
                            }}
                            placeholder={selectedTags.length === 0 && !inputValue ? "请输入要添加的标签，回车保存" : ""}
                            className="min-h-[22px] min-w-[120px] flex-1 bg-transparent text-sm leading-[22px] text-[#212121] outline-none placeholder-[#86909c]"
                        />
                        <span className="absolute right-3 top-0 flex h-full items-center text-[14px] leading-[22px] text-[#999]">
                            {inputValue.length}/{TAG_NAME_MAX_LENGTH}
                        </span>
                    </div>

                    <div className="flex flex-col gap-2 pt-1">
                        <div className="text-[14px] font-medium leading-5 text-[#212121]">已有标签</div>
                        <div className="flex flex-wrap gap-1">
                            {tags.length === 0 && (
                                <span className="text-[12px] text-[#86909c]">暂无标签</span>
                            )}
                            {tags.map((tag) => {
                                const isSelected = selectedTagIds.includes(tag.id);
                                return (
                                    <span
                                        key={tag.id}
                                        onClick={() => toggleTag(tag.id)}
                                        className={`flex h-7 items-center justify-center gap-1 rounded-[4px] px-2 text-[12px] leading-[20px] transition-colors ${isSelected
                                            ? "cursor-default bg-primary/10 text-[#165dff]"
                                            : "cursor-pointer bg-[#f2f3f5] text-[#4e5969] hover:bg-[#e5e6eb]"
                                            }`}
                                    >
                                        <span className="max-w-[180px] truncate" title={tag.name}>
                                            {truncateString(tag.name, TAG_DISPLAY_MAX_LENGTH)}
                                        </span>
                                        <button
                                            type="button"
                                            className="flex items-center justify-center text-[#86909c] hover:text-[#f53f3f] disabled:cursor-not-allowed disabled:text-[#c9cdd4]"
                                            onClick={(event) => {
                                                event.stopPropagation();
                                                void handleDeleteTag(tag);
                                            }}
                                            disabled={deletingTagId === tag.id}
                                        >
                                            <Trash2 className="size-3" />
                                        </button>
                                    </span>
                                );
                            })}
                        </div>
                    </div>
                </div>
                <div className="mt-2 flex h-16 shrink-0 items-center justify-end gap-3 border-none px-6 py-3">
                    <button
                        type="button"
                        className="h-8 rounded-[6px] border border-[#d9d9d9] bg-white px-4 text-[14px] font-normal text-[#1d2129] transition-colors hover:bg-[#f7f8fa]"
                        onClick={() => handleOpenChange(false)}
                    >
                        取消
                    </button>
                    <button
                        type="button"
                        className="h-8 rounded-[6px] bg-[#335CFF] px-4 text-[14px] font-normal text-white transition-colors hover:bg-[#5A7EFF] disabled:cursor-not-allowed disabled:opacity-60"
                        onClick={() => void handleSave()}
                        disabled={loading || !isEditable}
                    >
                        确认
                    </button>
                </div>
            </DialogContent>
        </Dialog>
    );
}
