import { PromptIcon } from '@/components/bs-icons/prompt';
import { Button } from '@/components/bs-ui/button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { useTranslation } from 'react-i18next';
import { CrossCircledIcon } from '@radix-ui/react-icons';
import { cname } from '@/components/bs-ui/utils';
import { useState } from 'react';
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';

function DragItem({className = '', data, children, onCancel}) {
    return <div className={cname('h-7 w-32 relative rounded-xl border flex place-items-center', className)}>
        <CrossCircledIcon onClick={(e) => {e.stopPropagation(); onCancel(data.id)}}
            className='text-gray-400 absolute top-[-6px] right-[-6px] cursor-pointer'/>
        <div className='bg-gray-500 rounded-full w-[26px] h-full text-center'>
            <span className='text-slate-50 font-bold'>{data.index}</span>
        </div>
        <div className='ml-2'>
            {children}
        </div>
    </div>
}

export default function MarkLabel({open, onClose}) {
    const { t } = useTranslation()
    const init = [
        {label:'标签一', value:'01', selected:false, edit:false},
        {label:'标签二', value:'02', selected:true, edit:false},
        {label:'标签三', value:'03', selected:false, edit:false},
        {label:'标签四', value:'04', selected:true, edit:false}
      ]
    const [labels, setLabels] = useState(init)
    const [selected, setSelected] = useState(init.filter(l => l.selected))

    const handleCancel = () => {
        onClose(false)
    }
    const handleConfirm = () => {
        onClose(false)
    }
    const handleSelect = (id) => {
        setLabels(pre => {
            const newData = pre.map(l => l.value === id ? {...l, selected:!l.selected} : l)
            const select = newData.find(d => d.value === id && d.selected)
            setSelected(select ? [...selected, select] : pre => pre.filter(d => d.value !== id))
            return newData
        })
    }
    // useEffect(() => {
    //     setSelected(labels.filter(l => l.selected))
    // }, [labels])
    const handleDelete = (id) => {
        setSelected(pre => pre.filter(d => d.value !== id))
        setLabels(pre => pre.map(d => d.value === id ? {...d, selected:!d.selected} : d))
    }
    const handleDragEnd = (result) => {
        if(!result.destination) return
        const newData = selected
        const [moveItem] = newData.splice(result.source.index, 1)
        newData.splice(result.destination.index, 0, moveItem)
        setSelected(newData)
        setFlag(false)
    }

    const [flag, setFlag] = useState(false) // 解决拖拽映射位置错位

    return <Dialog open={open} onOpenChange={onClose}>
        <DialogContent className='h-[800px] max-w-[1200px]'>
            <DialogHeader>
                <DialogTitle className='flex items-center space-x-2'>
                    <PromptIcon/>
                    <span className='text-sm text-gray-500'>操作提示：在左侧选择要展示的标签，在右侧拖拽进行排序</span>
                </DialogTitle>
            </DialogHeader>
            <div className='h-[650px] w-full grid grid-cols-[70%_30%]'>
                <div className='ml-10'>
                    <div className='w-full relative top-[50%] transform -translate-y-[50%]'>
                        {labels.map(l => <Button onClick={() => handleSelect(l.value)} 
                        className={`ml-4 mt-4 ${l.selected && 'bg-blue-300 hover:bg-blue-300'} w-[100px]`}>{l.label}</Button>)}
                    </div>
                </div>
                <div className='border-l text-gray-500'>
                    <div className='ml-4'>
                        <span className='text-xl font-bold'>已选：10/20</span>
                        <DragDropContext onDragEnd={handleDragEnd} onDragStart={() => setFlag(true)} onDragUpdate={() => setFlag(true)}>
                            <Droppable droppableId={'list'}>
                                {(provided) => (
                                    <div {...provided.droppableProps} ref={provided.innerRef}>
                                        {selected.map((b,index) => (
                                            <Draggable key={'drag' + b.value} draggableId={'drag' + b.value} index={index}>
                                                {(provided) => (
                                                    <div ref={provided.innerRef} {...provided.draggableProps} {...provided.dragHandleProps} 
                                                        style={flag ? { ...provided.draggableProps.style, position:'relative', left:0, top:0 } : {...provided.draggableProps.style}}>
                                                        <DragItem  onCancel={handleDelete} data={{index:index + 1, id:b.value}} className='mt-4'>
                                                            <span className='font-bold'>{b.label}</span>
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