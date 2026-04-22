import { GripVertical, Plus, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';
import { getAllLabelsApi, updateHomeLabelApi } from '~/api/apps';
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "~/components";
import { useToastContext } from "~/Providers";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";

const MAX_HOME_LABELS = 10;

type HomeTag = { label: string; value: string | number };
type LabelRow = { label: string; value: string | number; selected: boolean };

type MarkLabelProps = {
    open: boolean;
    home: HomeTag[];
    onClose: (saved: boolean) => void;
};

export default function MarkLabel({ open, home, onClose }: MarkLabelProps) {
    const [labels, setLabels] = useState<LabelRow[]>([]);
    const [selected, setSelected] = useState<HomeTag[]>([]);

    const { showToast } = useToastContext();
    const localize = useLocalize();

    useEffect(() => {
        async function init() {
            const all = (await getAllLabelsApi()) as { data: { data: { id: string | number; name: string }[] } };
            const newData = all.data.data.map((d) => {
                const res = home.find((h) => String(h.value) === String(d.id));
                return res
                    ? { label: d.name, value: d.id, selected: true }
                    : { label: d.name, value: d.id, selected: false };
            });
            setLabels(newData);
            setSelected(home.map((h) => ({ label: h.label, value: h.value })));
        }
        init();
    }, [home]);

    const handleCancel = () => {
        onClose(false);
    };

    const handleConfirm = async () => {
        await updateHomeLabelApi(selected.map((s) => s.value));
        onClose(true);
    };

    const handleSelect = (id: string | number) => {
        setLabels((pre) => {
            const newData = pre.map((l) =>
                String(l.value) === String(id) ? { ...l, selected: !l.selected } : l,
            );
            const selectedCount = newData.filter((d) => d.selected).length;
            if (selectedCount > MAX_HOME_LABELS) {
                showToast({ message: localize('com_label_max_selection'), status: 'warning' });
                return pre;
            }
            const toggled = newData.find((d) => String(d.value) === String(id));
            setSelected((prevSelected) => {
                if (toggled?.selected) {
                    const rest = prevSelected.filter((s) => String(s.value) !== String(id));
                    return [...rest, { label: toggled.label, value: toggled.value }];
                }
                return prevSelected.filter((s) => String(s.value) !== String(id));
            });
            return newData;
        });
    };

    const handleDelete = (id: string | number) => {
        setSelected((pre) => pre.filter((d) => String(d.value) !== String(id)));
        setLabels((pre) =>
            pre.map((d) => (String(d.value) === String(id) ? { ...d, selected: false } : d)),
        );
    };

    const handleDragEnd = (result: { destination?: { index: number } | null; source: { index: number } }) => {
        const { destination, source } = result;
        if (!destination) return;
        setSelected((prev) => {
            const next = [...prev];
            const [moveItem] = next.splice(source.index, 1);
            next.splice(destination.index, 0, moveItem);
            return next;
        });
    };

    return (
        <Dialog
            open={open}
            onOpenChange={(nextOpen) => {
                if (!nextOpen) onClose(false);
            }}
        >
            <DialogContent
                close={false}
                className={cn(
                    'flex flex-col gap-0 overflow-hidden p-0',
                    // H5（≤768px）：全屏覆盖，同设计稿竖屏布局
                    'max-[768px]:fixed max-[768px]:inset-0 max-[768px]:z-[100] max-[768px]:h-[100dvh] max-[768px]:max-h-none max-[768px]:w-full max-[768px]:max-w-none max-[768px]:translate-x-0 max-[768px]:translate-y-0 max-[768px]:rounded-none',
                    'max-[768px]:pt-[env(safe-area-inset-top)]',
                    // PC（≥769px）：居中、左右各 40px 边距、限高限宽、双栏
                    'min-[769px]:left-1/2 min-[769px]:top-1/2 min-[769px]:h-[80vh] min-[769px]:max-h-[800px] min-[769px]:w-[calc(100vw-80px)] min-[769px]:max-w-[800px] min-[769px]:-translate-x-1/2 min-[769px]:-translate-y-1/2 min-[769px]:rounded-xl',
                )}
            >
                <button
                    type="button"
                    onClick={handleCancel}
                    aria-label={localize('com_ui_close')}
                    className="absolute right-3 top-3 z-20 hidden items-center justify-center rounded-md p-1 text-[#4E5969] hover:bg-[#F2F3F5] max-[768px]:inline-flex max-[768px]:top-[max(0.75rem,env(safe-area-inset-top))]"
                >
                    <X className="size-5" />
                </button>
                <DialogHeader className="shrink-0 space-y-2 px-5 pb-3 pt-5 text-left max-[768px]:pr-12">
                    <div className="flex flex-row flex-wrap items-baseline gap-x-2 gap-y-1 min-[769px]:gap-x-3">
                        <DialogTitle className="text-base font-semibold leading-snug text-[#1D2129]">
                            {localize('com_label_settings_title')}
                        </DialogTitle>
                        <span className="text-sm font-normal leading-snug text-[#86909C] min-[769px]:hidden">
                            {localize('com_label_settings_subtitle_mobile')}
                        </span>
                        <span className="hidden text-sm font-normal leading-snug text-[#86909C] min-[769px]:inline">
                            {localize('com_label_settings_subtitle')}
                        </span>
                    </div>
                </DialogHeader>

                <div className="flex min-h-0 flex-1 flex-col border-t border-[#E5E6EB] min-[769px]:flex-row">
                    <div className="flex min-h-0 min-w-0 flex-col border-[#E5E6EB] max-[768px]:max-h-[min(42vh,360px)] max-[768px]:flex-none min-[769px]:flex-1 min-[769px]:border-r">
                        <div className="shrink-0 px-4 pb-2 pt-3 text-sm font-medium text-[#1D2129]">
                            {localize('com_label_all_tags')}
                        </div>
                        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4 max-[768px]:pb-3">
                            <div className="flex flex-wrap gap-2">
                                {labels.map((l) => (
                                    <button
                                        key={l.value}
                                        type="button"
                                        onClick={() => handleSelect(l.value)}
                                        className={cn(
                                            'inline-flex max-w-full items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm transition-colors',
                                            l.selected
                                                ? 'border-[#335CFF] bg-[#E8F0FF] text-[#335CFF]'
                                                : 'border-[#E5E6EB] bg-white text-[#4E5969] hover:bg-[#F7F8FA]',
                                        )}
                                    >
                                        <span className="truncate">{l.label}</span>
                                        {l.selected ? (
                                            <X className="size-3.5 shrink-0 opacity-80" strokeWidth={2.5} />
                                        ) : (
                                            <Plus className="size-3.5 shrink-0 opacity-60" strokeWidth={2.5} />
                                        )}
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>

                    <div className="flex min-h-0 min-w-0 flex-1 flex-col border-t border-[#E5E6EB] min-[769px]:border-t-0">
                        <div className="shrink-0 px-4 pb-2 pt-3 text-sm font-medium text-[#1D2129] max-[768px]:pt-2">
                            <span>{localize('com_label_display_tags')}</span>
                            <span className="ml-2 font-normal text-[#86909C]">
                                {selected.length}/{MAX_HOME_LABELS}
                            </span>
                        </div>
                        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4 max-[768px]:pb-3">
                            <DragDropContext onDragEnd={handleDragEnd}>
                                <Droppable droppableId="home-label-order">
                                    {(dropProvided) => (
                                        <div
                                            ref={dropProvided.innerRef}
                                            {...dropProvided.droppableProps}
                                            className="flex flex-col gap-2"
                                        >
                                            {selected.map((b, index) => (
                                                <Draggable
                                                    key={`tag-${String(b.value)}`}
                                                    draggableId={`tag-${String(b.value)}`}
                                                    index={index}
                                                >
                                                    {(dragProvided) => (
                                                        <div
                                                            ref={dragProvided.innerRef}
                                                            {...dragProvided.draggableProps}
                                                            {...dragProvided.dragHandleProps}
                                                            className="flex w-full cursor-grab items-center gap-2 rounded-lg border border-[#E5E6EB] bg-white px-2 py-2.5 shadow-sm active:cursor-grabbing"
                                                        >
                                                            <GripVertical className="size-4 shrink-0 text-[#C9CDD4]" />
                                                            <span className="min-w-0 flex-1 truncate text-sm font-medium text-[#1D2129]">
                                                                {b.label}
                                                            </span>
                                                            <button
                                                                type="button"
                                                                className="inline-flex shrink-0 rounded p-1 text-[#86909C] hover:bg-[#F2F3F5] hover:text-[#4E5969]"
                                                                aria-label={localize('com_label_remove_display')}
                                                                onMouseDown={(e) => e.stopPropagation()}
                                                                onTouchStart={(e) => e.stopPropagation()}
                                                                onClick={(e) => {
                                                                    e.stopPropagation();
                                                                    handleDelete(b.value);
                                                                }}
                                                            >
                                                                <X className="size-4" />
                                                            </button>
                                                        </div>
                                                    )}
                                                </Draggable>
                                            ))}
                                            {dropProvided.placeholder}
                                        </div>
                                    )}
                                </Droppable>
                            </DragDropContext>
                        </div>
                    </div>
                </div>

                <DialogFooter className="shrink-0 gap-3 border-t border-[#E5E6EB] px-5 py-4 max-[768px]:!flex-row max-[768px]:!flex-nowrap max-[768px]:pb-[max(1rem,env(safe-area-inset-bottom))] min-[769px]:justify-end">
                    <Button
                        variant="outline"
                        className="h-10 min-w-[96px] rounded-lg border-[#E5E6EB] bg-white text-[#4E5969] hover:bg-[#F7F8FA] max-[768px]:h-11 max-[768px]:min-w-0 max-[768px]:flex-1"
                        onClick={handleCancel}
                    >
                        {localize('com_label_cancel')}
                    </Button>
                    <Button
                        className="h-10 min-w-[96px] rounded-lg bg-[#335CFF] hover:bg-[#2A4AE0] max-[768px]:h-11 max-[768px]:min-w-0 max-[768px]:flex-1"
                        onClick={handleConfirm}
                    >
                        {localize('com_label_save')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
