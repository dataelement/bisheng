import { PromptIcon } from '@/components/bs-icons/prompt';
import { Button } from '@/components/bs-ui/button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { useToast } from '@/components/bs-ui/toast/use-toast';
import { cname } from '@/components/bs-ui/utils';
import { getAllLabelsApi, updateHomeLabelApi } from "@/controllers/API/label";
import { captureAndAlertRequestErrorHoc } from '@/controllers/request';
import { CircleX } from 'lucide-react';
import { useEffect, useState } from 'react';
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';
import { useTranslation } from 'react-i18next';

function DragItem({ className = '', data, children, onCancel }) {
    return <div className={cname('h-7 w-32 relative rounded-xl border flex place-items-center', className)}>
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
    const { t } = useTranslation()
    const [labels, setLabels] = useState([])
    const [selected, setSelected] = useState([])
    const { message } = useToast()

    useEffect(() => {
        async function init() {
            const all = await getAllLabelsApi()
            const newData = all.data.map(d => {
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
        await captureAndAlertRequestErrorHoc(updateHomeLabelApi(selected.map(s => s.value)))
        onClose(false)
    }

    const handleSelect = (id) => {
        setLabels(pre => {
            const newData = pre.map(l => l.value === id ? { ...l, selected: !l.selected } : l)
            if (newData.filter(d => d.selected).length > 10) {
                message({
                    title: t('prompt'),
                    variant: 'warning',
                    description: '最多选择10个标签'
                })
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
        <DialogContent className='h-[80%] max-w-[70%] overflow-hidden'>
            <DialogHeader>
                <DialogTitle className='flex items-center space-x-2'>
                    <PromptIcon />
                    <span className='text-sm text-gray-500'>{t('chat.operationTips')}</span>
                </DialogTitle>
            </DialogHeader>
            <div className='h-[650px] w-full grid grid-cols-[70%_30%]'>
                <div className='ml-10'>
                    <div className='w-full relative top-[50%] transform -translate-y-[50%]'>
                        {
                            labels.map(l =>
                                <Button onClick={() => handleSelect(l.value)}
                                    size='sm'
                                    className={`ml-4 mt-4 p-1 ${!l.selected && 'bg-blue-300 hover:bg-blue-300'} w-[120px]`}>
                                    <span className='truncate'>{l.label}</span>
                                </Button>)
                        }
                    </div>
                </div>
                <div className='border-l text-gray-500'>
                    <div className='ml-4'>
                        <span className='text-md font-bold'>{t('chat.selected')}：{selected.length}/10</span>
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
            <DialogFooter className='absolute bottom-6 right-6'>
                <Button variant="outline" className="h-10 w-[120px] px-16" onClick={handleCancel}>{t('cancel')}</Button>
                <Button className="px-16 h-10 w-[120px]" onClick={handleConfirm}>{t('save')}</Button>
            </DialogFooter>
        </DialogContent>
    </Dialog>
}