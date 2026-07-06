/**
 * F035 Track H: knowledge dropdown of the task-mode input. Multi-selects
 * personal knowledge spaces and organization knowledge bases; selections show
 * as removable chips above the textarea (spec §1, fig.7).
 * Data sources mirror the daily input's ChatKnowledge: spaces from
 * /knowledge/space/{mine,joined}, org KBs from /api/v1/knowledge (getKnowledgeInfo).
 */
import { Check, ChevronDown, Loader2, SearchIcon } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getDepartmentSpacesApi, getJoinedSpacesApi, getMineSpacesApi } from '~/api/knowledge';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Input,
} from '~/components/ui';
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
}

export function KnowledgeSpaceSelect({ value, disabled = false, onChange }: KnowledgeSpaceSelectProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const { data: bsConfig } = useGetBsConfig();
    const [open, setOpen] = useState(false);
    const [keyword, setKeyword] = useState('');

    // Personal knowledge spaces: mine + joined + department merged (same as ChatKnowledge).
    const { data: spaces = [], isFetching: spaceFetching } = useQuery({
        queryKey: ['taskModeKnowledgeSpaces'],
        queryFn: async () => {
            const [mine, joined, department] = await Promise.all([
                getMineSpacesApi(),
                getJoinedSpacesApi(),
                getDepartmentSpacesApi(),
            ]);
            const seen = new Set<string | number>();
            const merged: any[] = [];
            for (const s of [...mine, ...joined, ...department]) {
                if (seen.has(s.id)) continue;
                seen.add(s.id);
                merged.push(s);
            }
            return merged;
        },
        enabled: open,
        refetchOnWindowFocus: false,
    });

    // Org knowledge bases (use-permission filtered server-side).
    const orgEnabled = (bsConfig as any)?.knowledgeBase?.enabled !== false;
    const { data: orgKbs = [], isFetching: orgFetching } = useGetOrgToolList({ page: 1, page_size: 50 });

    useEffect(() => {
        if (!open) setKeyword('');
    }, [open]);

    const kw = keyword.trim().toLowerCase();
    const filteredSpaces = useMemo(
        () => (kw ? spaces.filter((s: any) => s.name?.toLowerCase().includes(kw)) : spaces),
        [spaces, kw],
    );
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
                status: 'error',
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
                        active ? 'text-blue-600' : 'text-[#4E5969]',
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
                    <span className="truncate max-w-[min(30vw,120px)]">{localize('com_ui_knowledge_space')}</span>
                    <ChevronDown size={14} className="text-slate-400" />
                </button>
            </DropdownMenuTrigger>

            <DropdownMenuContent
                align="start"
                className="flex max-h-[380px] w-[280px] flex-col gap-2 overflow-hidden rounded-2xl border-slate-100 p-3 shadow-xl"
            >
                <div className="relative shrink-0">
                    <SearchIcon className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
                    <Input
                        className="h-[28px] rounded-[6px] border border-[#ECECEC] bg-white pl-8 text-xs focus-visible:ring-1 focus-visible:ring-blue-500/20"
                        placeholder={localize('com_chat_knowledge_placeholder_search_space')}
                        value={keyword}
                        onChange={(e) => setKeyword(e.target.value)}
                        onClick={(e) => e.stopPropagation()}
                        onKeyDown={(e) => e.stopPropagation()}
                    />
                </div>

                <div className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto">
                    {/* Personal knowledge spaces */}
                    <p className="px-1 py-1 text-xs font-medium text-slate-400">
                        {localize('com_ui_knowledge_space')}
                    </p>
                    {filteredSpaces.map((item: any) => renderRow(item, 'space'))}
                    {!isFetching && filteredSpaces.length === 0 && (
                        <p className="px-1 py-1.5 text-center text-xs text-slate-300">
                            {localize('com_chat_knowledge_empty_no_spaces')}
                        </p>
                    )}

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
