/**
 * F035 Track H: knowledge dropdown of the task-mode input. Multi-selects
 * personal knowledge spaces and organization knowledge bases; selections show
 * as removable chips above the textarea (spec §1, fig.7).
 * Spaces use the visible cursor endpoint; organization knowledge bases keep their own catalog.
 */
import { Check, ChevronDown, Loader2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useVisibleKnowledgeSpaces } from '~/hooks/useVisibleKnowledgeSpaces';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '~/components/ui';
import { Button, SearchInput } from '@bisheng/ui';
import { useGetBsConfig, useGetOrgToolList } from '~/hooks/queries/data-provider';
import { useLocalize } from '~/hooks';
import { useToastContext } from '~/Providers';
import type { TaskModeKnowledgeItem } from '~/store/linsight';
import { cn } from '~/utils';

const MAX_SELECTED_PER_TYPE = 50;

interface KnowledgeSpaceSelectProps {
    value: TaskModeKnowledgeItem[];
    disabled?: boolean;
    onChange: (items: TaskModeKnowledgeItem[]) => void;
    /** Toolbar out of room (see useContainerCompact): collapse label to icon. */
    compact?: boolean;
}

export function KnowledgeSpaceSelect({ value, disabled = false, onChange, compact = false }: KnowledgeSpaceSelectProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const { data: bsConfig } = useGetBsConfig();
    const [open, setOpen] = useState(false);
    const [keyword, setKeyword] = useState('');

    const { spaces, isFetching: spaceFetching, isError: spaceError, retry: retrySpaces,
        hasMore, loadMore } = useVisibleKnowledgeSpaces({ enabled: open, keyword });

    // Organization knowledge bases keep their independent server-filtered catalog.
    const orgEnabled = (bsConfig as any)?.knowledgeBase?.enabled !== false;
    const { data: orgKbs = [], isFetching: orgFetching } = useGetOrgToolList({ page: 1, page_size: 50 });

    useEffect(() => {
        if (!open) setKeyword('');
    }, [open]);

    const kw = keyword.trim().toLowerCase();
    const filteredOrgKbs = useMemo(
        () => (kw ? (orgKbs || []).filter((k: any) => k.name?.toLowerCase().includes(kw)) : orgKbs || []),
        [orgKbs, kw],
    );

    const handleToggle = (item: any, type: TaskModeKnowledgeItem['type']) => {
        const itemKey = String(item.id);
        const exists = value.some((i) => String(i.id) === itemKey && i.type === type);
        if (exists) {
            onChange(value.filter((i) => !(String(i.id) === itemKey && i.type === type)));
            return;
        }
        if (value.filter((i) => i.type === type).length >= MAX_SELECTED_PER_TYPE) {
            showToast({
                message:
                    type === 'space'
                        ? localize('com_chat_knowledge_toast_space_limit')
                        : localize('com_chat_knowledge_toast_org_limit'),
                status: 'warning',
            });
            return;
        }
        onChange([{ id: itemKey, name: item.name, type }, ...value]);
    };

    const renderRow = (item: any, type: TaskModeKnowledgeItem['type']) => {
        const isChecked = value.some((i) => String(i.id) === String(item.id) && i.type === type);
        return (
            <DropdownMenuItem
                key={`${type}-${item.id}`}
                onSelect={(e) => {
                    e.preventDefault();
                    handleToggle(item, type);
                }}
                className="flex cursor-pointer items-center gap-2.5 rounded-lg px-1 py-2 outline-none hover:bg-slate-50 focus:bg-slate-50"
            >
                <div
                    className={cn(
                        'flex size-4 shrink-0 items-center justify-center rounded border transition-colors',
                        isChecked ? 'border-blue-600 bg-blue-600' : 'border-slate-300 bg-white',
                    )}
                >
                    {isChecked && <Check size={12} className="stroke-[3] text-white" />}
                </div>
                <span className="flex-1 truncate text-[13px] leading-none text-slate-700">{item.name}</span>
            </DropdownMenuItem>
        );
    };

    const active = value.length > 0;
    const isFetching = spaceFetching || orgFetching;

    return (
        <DropdownMenu open={open} onOpenChange={setOpen}>
            <DropdownMenuTrigger asChild disabled={disabled}>
                <button
                    type="button"
                    className={cn(
                        'flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2 text-xs font-normal outline-none transition-colors hover:bg-black/5',
                        // Active highlight uses brand-600 to match the checked-checkbox
                        // color in the picker rows below (renderRow).
                        active ? 'text-blue-600' : 'text-text-2',
                        disabled && 'cursor-not-allowed opacity-50',
                    )}
                >
                    {/* book-one.svg has a baked #999999 stroke, so an <img> can't
                        follow the active color. Render it as a CSS mask instead so the
                        icon turns brand-500 when active (mirrors ChatKnowledge). */}
                    <span
                        aria-hidden
                        className={cn(
                            'block size-4 shrink-0',
                            active ? 'bg-blue-600' : 'bg-[#999999]',
                        )}
                        style={{
                            WebkitMaskImage: `url(${__APP_ENV__.BASE_URL || ''}/assets/channel/book-one.svg)`,
                            maskImage: `url(${__APP_ENV__.BASE_URL || ''}/assets/channel/book-one.svg)`,
                            WebkitMaskRepeat: 'no-repeat', maskRepeat: 'no-repeat',
                            WebkitMaskPosition: 'center', maskPosition: 'center',
                            WebkitMaskSize: 'contain', maskSize: 'contain',
                        }}
                    />
                    {!compact && <span className="truncate">{localize('com_ui_knowledge_space')}</span>}
                    <ChevronDown size={14} className="text-slate-400" />
                </button>
            </DropdownMenuTrigger>

            <DropdownMenuContent
                align="start"
                className="flex max-h-[380px] w-[280px] flex-col gap-2 overflow-hidden rounded-2xl border-slate-100 p-3 shadow-xl"
            >
                {/* Spec SearchInput; stopPropagation on the wrapper keeps every
                    click in the shell (magnifier, padding, clear) out of the
                    dropdown's own handlers. */}
                <div
                    className="shrink-0"
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                >
                    <SearchInput
                        placeholder={localize('com_chat_knowledge_placeholder_search_space')}
                        value={keyword}
                        onChange={(e) => setKeyword(e.target.value)}
                        clearLabel={localize('com_ui_clear')}
                    />
                </div>

                <div className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto">
                    {/* Personal knowledge spaces */}
                    <p className="px-1 py-1 text-xs font-medium text-slate-400">
                        {localize('com_ui_knowledge_space')}
                    </p>
                    {spaces.map((item) => renderRow(item, 'space'))}
                    {!isFetching && spaces.length === 0 && !spaceError && !hasMore && (
                        <p className="px-1 py-1.5 text-center text-xs text-slate-300">
                            {localize('com_chat_knowledge_empty_no_spaces')}
                        </p>
                    )}

                    {spaceError && <div role="alert" className="flex flex-col gap-2 text-body-sm text-text-3">
                        <span>{localize('dshChat.knowledgeLoadError')}</span>
                        <Button color="default" variant="outlined" onClick={() => { void retrySpaces(); }}>
                            {localize('dshChat.retryKnowledge')}
                        </Button>
                    </div>}
                    {hasMore && !spaceError && <Button color="default" variant="outlined" loading={spaceFetching} onClick={loadMore}>
                        {localize('dshChat.loadMoreKnowledge')}
                    </Button>}

                    {/* Organization knowledge bases */}
                    {orgEnabled && (
                        <>
                            <p className="mt-1 px-1 py-1 text-xs font-medium text-slate-400">
                                {localize('com_tools_org_knowledge')}
                            </p>
                            {filteredOrgKbs.map((item: any) => renderRow(item, 'org'))}
                            {!isFetching && filteredOrgKbs.length === 0 && (
                                <p className="px-1 py-1.5 text-center text-xs text-slate-300">
                                    {localize('com_chat_knowledge_empty_no_org_kbs')}
                                </p>
                            )}
                        </>
                    )}

                    {isFetching && (
                        <div className="flex justify-center py-3">
                            <Loader2 size={16} className="animate-spin text-slate-300" />
                        </div>
                    )}
                </div>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}
