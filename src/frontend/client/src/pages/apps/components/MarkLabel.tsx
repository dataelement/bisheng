




import { CircleX, LightbulbIcon, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';
import { getAllLabelsApi, updateHomeLabelApi } from '~/api/apps';
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "~/components";
import { useToastContext } from "~/Providers";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";

function DragItem({ className = '', data, children, onCancel }) {
    return <div className={cn('h-7 w-32 relative rounded-md rounded-l-xl border flex place-items-center', className)}>
        <CircleX onClick={(e) => { e.stopPropagation(); onCancel(data.id) }}
            className='text-gray-400 absolute top-[-6px] right-[-6px] cursor-pointer size-4' />
        <div className='bg-gray-500 rounded-full w-[26px] h-full text-center'>
            <span className='text-slate-50 font-bold text-sm'>{data.index}</span>
        </div>
        <div className='ml-2 truncate'>
            {children}
        </div>
    </div>
}

export default function MarkLabel({ open, home, onClose }) {
    const [labels, setLabels] = useState([])
    const [selected, setSelected] = useState([])

    const { showToast } = useToastContext();
    const localize = useLocalize();

    useEffect(() => {
        async function init() {
            const all = await getAllLabelsApi()
            const newData = all.data.data.map(d => {
                const res = home.find(h => h.value === d.id)
                return res ? { label: d.name, value: d.id, selected: true } : { label: d.name, value: d.id, selected: false }
            })
            setLabels(newData)
            setSelected(home)
        }
        init()
    }, [home])

    const handleCancel = () => {
        onClose(false)
    }

    const handleConfirm = async () => {
        await updateHomeLabelApi(selected.map(s => s.value))
        // TODO 重新加载列表
        onClose(true)
    }

    const handleSelect = (id) => {
        setLabels(pre => {
            const newData = pre.map(l => l.value === id ? { ...l, selected: !l.selected } : l)
            if (newData.filter(d => d.selected).length > 10) {
                showToast({ message: localize('com_label_max_selection'), status: 'warning' });
                return pre
            }
            const select = newData.find(d => d.value === id && d.selected)
            setSelected(select ? [...selected, select] : pre => pre.filter(d => d.value !== id))
            return newData
        })
    }

    const handleDelete = (id) => {
        setSelected(pre => pre.filter(d => d.value !== id))
        setLabels(pre => pre.map(d => d.value === id ? { ...d, selected: !d.selected } : d))
    }

    const handleDragEnd = (result) => {
        if (!result.destination) return
        const newData = selected
        const [moveItem] = newData.splice(result.source.index, 1)
        newData.splice(result.destination.index, 0, moveItem)
        setSelected(newData)
        setFlag(false)
    }

    const [flag, setFlag] = useState(false) // 解决拖拽映射位置错位

    return <Dialog open={open} onOpenChange={onClose}>
        <DialogContent close={false} className='max-w-[70%] overflow-hidden max-[768px]:h-screen max-[768px]:w-screen max-[768px]:max-w-none max-[768px]:rounded-none max-[768px]:p-0'>
            <button
                type="button"
                onClick={handleCancel}
                aria-label={localize('com_label_cancel')}
                className='absolute right-3 top-3 z-20 hidden items-center justify-center rounded-md p-1 text-[#4E5969] hover:bg-[#F2F3F5] max-[768px]:inline-flex'
            >
                <X className='size-5' />
            </button>
            <DialogHeader className='h-20 max-[768px]:h-auto max-[768px]:border-b max-[768px]:px-4 max-[768px]:pb-3 max-[768px]:pt-4'>
                <DialogTitle className='flex items-start space-x-2 max-[768px]:flex-col max-[768px]:space-x-0 max-[768px]:space-y-1'>
                    <LightbulbIcon />
                    <span className='text-sm text-gray-500 max-[768px]:hidden'>{localize('com_label_operation_tip')}</span>
                    <span className='hidden text-sm text-gray-500 max-[768px]:inline'>
                        {localize('com_label_operation_tip_mobile')}
                    </span>
                </DialogTitle>
            </DialogHeader>
            <div className='h-[600px] w-full grid grid-cols-[70%_30%] max-[768px]:h-[calc(100vh-154px)] max-[768px]:grid-cols-1 max-[768px]:overflow-y-auto max-[768px]:px-4 max-[768px]:pb-24 max-[768px]:pt-3'>
                <div className='ml-10 max-[768px]:ml-0'>
                    <div className='w-full relative'>
                        {
                            labels.map(l =>
                                <Button onClick={() => handleSelect(l.value)}
                                    size='sm'
                                    className={`ml-4 mt-4 p-1 ${!l.selected && 'bg-primary/40 hover:bg-primary/70'} w-[120px]`}>
                                    <span className='truncate text-xs'>{l.label}</span>
                                </Button>)
                        }
                    </div>
                </div>
                <div className='border-l text-gray-500 max-[768px]:mt-4 max-[768px]:border-l-0 max-[768px]:border-t max-[768px]:pt-4'>
                    <div className='ml-4 max-[768px]:ml-0'>
                        <span className='text-md font-bold'>{localize('com_label_selected', { 0: selected.length })}</span>
                        <DragDropContext onDragEnd={handleDragEnd} onDragStart={() => setFlag(true)} onDragUpdate={() => setFlag(true)}>
                            <Droppable droppableId={'list'}>
                                {(provided) => (
                                    <div {...provided.droppableProps} ref={provided.innerRef}>
                                        {selected.map((b, index) => (
                                            <Draggable key={'drag' + b.value} draggableId={'drag' + b.value} index={index}>
                                                {(provided) => (
                                                    <div ref={provided.innerRef} {...provided.draggableProps} {...provided.dragHandleProps}
                                                        style={flag ? { ...provided.draggableProps.style, position: 'relative', left: 0, top: 0 } : { ...provided.draggableProps.style }}>
                                                        <DragItem onCancel={handleDelete} data={{ index: index + 1, id: b.value }} className='mt-4 w-[170px]'>
                                                            <span className='font-bold text-sm'>{b.label}</span>
                                                        </DragItem>
                                                    </div>
                                                )}
                                            </Draggable>
                                        ))}
                                        {provided.placeholder}
                                    </div>
                                )}
                            </Droppable>
                        </DragDropContext>
                    </div>
                </div>
            </div>
            <DialogFooter className='absolute bottom-6 right-6 max-[768px]:fixed max-[768px]:bottom-0 max-[768px]:left-0 max-[768px]:right-0 max-[768px]:z-20 max-[768px]:w-full max-[768px]:!flex max-[768px]:!flex-row max-[768px]:items-center max-[768px]:justify-between max-[768px]:gap-3 max-[768px]:border-t max-[768px]:bg-white max-[768px]:px-4 max-[768px]:py-3'>
                <Button variant="outline" className="h-10 w-[120px] px-16 max-[768px]:!w-1/2 max-[768px]:px-0" onClick={handleCancel}>{localize('com_label_cancel')}</Button>
                <Button className="px-16 h-10 w-[120px] max-[768px]:!w-1/2 max-[768px]:px-0" onClick={handleConfirm}>{localize('com_label_save')}</Button>
            </DialogFooter>
        </DialogContent>
    </Dialog>
}