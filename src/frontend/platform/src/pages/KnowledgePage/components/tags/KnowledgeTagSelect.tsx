import { Badge } from "@/components/bs-ui/badge";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Checkbox } from "@/components/bs-ui/checkBox";
import { Input, SearchInput } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import {
    batchAddFileTagsApi,
    createKnowledgeTagApi,
    deleteKnowledgeTagApi,
    getKnowledgeTagsApi,
    KnowledgeTagItem,
    setFileTagsApi,
    updateKnowledgeTagApi
} from "@/controllers/API/knowledgeTags";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { Edit2, Plus, Tag as TagIcon, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

interface KnowledgeTagSelectProps {
    knowledgeId: string | number;
    fileIds: number[];
    initialTags?: KnowledgeTagItem[];
    children: React.ReactNode;
    onUpdate: () => void;
    isEditable?: boolean;
}

const TAG_NAME_MAX_LENGTH = 8;
const FILE_TAG_LIMIT = 5;

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
    const [keyword, setKeyword] = useState('');
    const [editingTagId, setEditingTagId] = useState<number | null>(null);
    const [editName, setEditName] = useState('');
    const fetchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const isBatch = fileIds.length > 1;
    const numericKnowledgeId = Number(knowledgeId);

    const syncSelectedTags = () => {
        if (isBatch) {
            setSelectedTagIds([]);
            return;
        }
        setSelectedTagIds(initialTags.map(tag => tag.id));
    };

    const fetchTags = async (searchKeyword: string) => {
        if (!numericKnowledgeId) return;
        const response = await captureAndAlertRequestErrorHoc(
            getKnowledgeTagsApi(numericKnowledgeId, {
                keyword: searchKeyword.trim() || undefined,
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
        syncSelectedTags();
        fetchTags(keyword);
    }, [open, numericKnowledgeId]);

    useEffect(() => {
        if (!open) return;
        if (fetchTimerRef.current) {
            clearTimeout(fetchTimerRef.current);
        }
        fetchTimerRef.current = setTimeout(() => {
            fetchTags(keyword);
        }, 250);

        return () => {
            if (fetchTimerRef.current) {
                clearTimeout(fetchTimerRef.current);
                fetchTimerRef.current = null;
            }
        };
    }, [keyword, open, numericKnowledgeId]);

    useEffect(() => {
        if (!open || isBatch) return;
        setSelectedTagIds(initialTags.map(tag => tag.id));
    }, [initialTags, isBatch, open]);

    const handleOpenChange = (nextOpen: boolean) => {
        setOpen(nextOpen);
        if (!nextOpen) {
            setKeyword('');
            setEditingTagId(null);
            setEditName('');
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

    const handleSingleFileTagToggle = async (tagId: number) => {
        const nextIds = selectedTagIds.includes(tagId)
            ? selectedTagIds.filter(id => id !== tagId)
            : [...selectedTagIds, tagId];

        if (nextIds.length > FILE_TAG_LIMIT) {
            toast({ variant: 'error', description: t('tagsCountLimitExceeded') });
            return;
        }

        const result = await captureAndAlertRequestErrorHoc(
            setFileTagsApi({
                knowledge_id: numericKnowledgeId,
                file_id: fileIds[0],
                tag_ids: nextIds
            })
        );

        if (result === false || result === 'canceled') {
            return;
        }

        setSelectedTagIds(nextIds);
        onUpdate();
    };

    const handleBatchAddTag = async (tagId: number, showSuccessToast = true) => {
        const result = await captureAndAlertRequestErrorHoc(
            batchAddFileTagsApi({
                knowledge_id: numericKnowledgeId,
                file_ids: fileIds,
                tag_ids: [tagId]
            })
        );

        if (result === false || result === 'canceled') {
            return;
        }

        setSelectedTagIds(prev => (prev.includes(tagId) ? prev : [...prev, tagId]));
        if (showSuccessToast) {
            toast({ variant: 'success', description: t('tagAdded') });
        }
        onUpdate();
    };

    const handleTagCheck = async (tagId: number) => {
        if (!isEditable) return;
        if (isBatch) {
            await handleBatchAddTag(tagId);
            return;
        }
        await handleSingleFileTagToggle(tagId);
    };

    const handleCreateTag = async () => {
        const tagName = keyword.trim();
        if (!validateTagName(tagName)) return;

        const result = await captureAndAlertRequestErrorHoc(
            createKnowledgeTagApi(numericKnowledgeId, tagName)
        );

        if (!result || result === 'canceled') {
            return;
        }

        const newTag = result as KnowledgeTagItem;
        setTags(prev => [newTag, ...prev.filter(tag => tag.id !== newTag.id)]);
        setKeyword('');
        toast({ variant: 'success', description: t('tagAdded') });
        if (isBatch) {
            await handleBatchAddTag(newTag.id, false);
            return;
        }
        await handleSingleFileTagToggle(newTag.id);
    };

    const handleStartEdit = (tag: KnowledgeTagItem) => {
        setEditingTagId(tag.id);
        setEditName(tag.name);
    };

    const handleUpdateTag = async (tagId: number) => {
        const tagName = editName.trim();
        setEditingTagId(null);

        if (!tagName) {
            setEditName('');
            return;
        }
        if (!validateTagName(tagName)) {
            return;
        }

        const currentTag = tags.find(tag => tag.id === tagId);
        if (currentTag?.name === tagName) {
            setEditName('');
            return;
        }

        const result = await captureAndAlertRequestErrorHoc(
            updateKnowledgeTagApi(numericKnowledgeId, tagId, tagName)
        );

        if (!result || result === 'canceled') {
            return;
        }

        const updatedTag = result as KnowledgeTagItem;
        setTags(prev => prev.map(tag => (tag.id === tagId ? updatedTag : tag)));
        toast({ variant: 'success', description: t('tagUpdated') });
        setEditName('');
        onUpdate();
    };

    const handleDeleteTag = (tag: KnowledgeTagItem) => {
        bsConfirm({
            title: t('prompt'),
            desc: t('confirmDeleteTag', { name: tag.name }),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteKnowledgeTagApi(numericKnowledgeId, tag.id)).then((result) => {
                    if (result === false || result === 'canceled') {
                        next();
                        return;
                    }
                    setTags(prev => prev.filter(item => item.id !== tag.id));
                    setSelectedTagIds(prev => prev.filter(id => id !== tag.id));
                    toast({ variant: 'success', description: t('tagDeleted') });
                    onUpdate();
                    next();
                });
            }
        });
    };

    const showCreate = useMemo(() => {
        const normalizedKeyword = keyword.trim().toLowerCase();
        if (!normalizedKeyword) return false;
        return !tags.some(tag => tag.name.trim().toLowerCase() === normalizedKeyword);
    }, [keyword, tags]);

    const selectedTags = useMemo(
        () => tags.filter(tag => selectedTagIds.includes(tag.id)),
        [tags, selectedTagIds]
    );

    return (
        <Popover open={open} onOpenChange={handleOpenChange}>
            <PopoverTrigger asChild>{children}</PopoverTrigger>
            <PopoverContent
                align="start"
                className="w-[320px] p-4"
                onClick={(event) => event.stopPropagation()}
            >
                <div className="space-y-4">
                    <SearchInput
                        placeholder={t('searchTags')}
                        value={keyword}
                        onChange={(event) => setKeyword(event.target.value)}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter' && showCreate && isEditable) {
                                event.preventDefault();
                                handleCreateTag();
                            }
                        }}
                    />

                    <div className="max-h-[260px] space-y-1 overflow-y-auto">
                        {tags.map((tag) => (
                            <div
                                key={tag.id}
                                className="group flex min-h-8 items-center justify-between rounded px-2 hover:bg-muted"
                            >
                                <div className="flex min-w-0 flex-1 items-center gap-2 py-1">
                                    <Checkbox
                                        id={`knowledge-tag-${tag.id}`}
                                        checked={selectedTagIds.includes(tag.id)}
                                        disabled={!isEditable || (isBatch && selectedTagIds.includes(tag.id))}
                                        onCheckedChange={() => handleTagCheck(tag.id)}
                                    />
                                    {editingTagId === tag.id ? (
                                        <Input
                                            autoFocus
                                            maxLength={TAG_NAME_MAX_LENGTH}
                                            className="h-7 px-2"
                                            value={editName}
                                            onChange={(event) => setEditName(event.target.value)}
                                            onBlur={() => handleUpdateTag(tag.id)}
                                            onKeyDown={(event) => {
                                                if (event.key === 'Enter') {
                                                    handleUpdateTag(tag.id);
                                                }
                                                if (event.key === 'Escape') {
                                                    setEditingTagId(null);
                                                    setEditName('');
                                                }
                                            }}
                                        />
                                    ) : (
                                        <Label
                                            htmlFor={`knowledge-tag-${tag.id}`}
                                            className="flex-1 cursor-pointer truncate"
                                        >
                                            {tag.name}
                                        </Label>
                                    )}
                                </div>

                                {isEditable && editingTagId !== tag.id && (
                                    <div className="ml-2 flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                                        <button
                                            className="rounded p-1 hover:bg-background"
                                            onClick={(event) => {
                                                event.stopPropagation();
                                                handleStartEdit(tag);
                                            }}
                                        >
                                            <Edit2 size={12} className="text-muted-foreground" />
                                        </button>
                                        <button
                                            className="rounded p-1 hover:bg-background"
                                            onClick={(event) => {
                                                event.stopPropagation();
                                                handleDeleteTag(tag);
                                            }}
                                        >
                                            <Trash2 size={12} className="text-muted-foreground" />
                                        </button>
                                    </div>
                                )}
                            </div>
                        ))}

                        {!tags.length && !showCreate && (
                            <div className="py-6 text-center text-sm text-muted-foreground">
                                {t('noTags')}
                            </div>
                        )}

                        {showCreate && isEditable && (
                            <button
                                className="flex w-full items-center rounded px-2 py-2 text-left text-sm text-primary hover:bg-primary/10"
                                onClick={handleCreateTag}
                            >
                                <Plus size={16} className="mr-2" />
                                {t('createTagWithName', { name: keyword.trim() })}
                            </button>
                        )}
                    </div>

                    {!isBatch && (
                        <div className="border-t pt-3">
                            <div className="mb-2 flex items-center justify-between text-xs text-muted-foreground">
                                <span>{t('selectedItems')}</span>
                                <span>{selectedTagIds.length}/{FILE_TAG_LIMIT}</span>
                            </div>
                            {selectedTags.length ? (
                                <div className="flex flex-wrap gap-1">
                                    {selectedTags.map((tag) => (
                                        <Badge key={tag.id} variant="secondary" className="h-6 gap-1 px-2 py-0">
                                            <TagIcon size={12} />
                                            <span className="max-w-[180px] truncate">{tag.name}</span>
                                            {isEditable && (
                                                <X
                                                    size={12}
                                                    className="cursor-pointer"
                                                    onClick={() => handleTagCheck(tag.id)}
                                                />
                                            )}
                                        </Badge>
                                    ))}
                                </div>
                            ) : (
                                <div className="text-xs text-muted-foreground">{t('noTagsSelected')}</div>
                            )}
                        </div>
                    )}
                </div>
            </PopoverContent>
        </Popover>
    );
}
