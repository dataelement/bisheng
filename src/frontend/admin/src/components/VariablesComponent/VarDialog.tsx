import cloneDeep from 'lodash-es/cloneDeep';
import { ArrowDownUp, Plus, X } from "lucide-react";
import { useContext, useState } from 'react';
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';
import { useTranslation } from 'react-i18next';
import { alertContext } from '../../contexts/alertContext';
import { generateUUID } from '../../utils';
import { Button } from '../bs-ui/button';
import { DialogContent, DialogFooter } from '../bs-ui/dialog';
import { Input } from '../bs-ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../bs-ui/tabs';

export default function VarDialog({ data, onSave, onClose }) {

    const [item, setItem] = useState(data)
    const { t } = useTranslation()

    const [errors, setErrors] = useState([])
    const { setErrorData } = useContext(alertContext);

    const handleSave = () => {
        // 校验
        const _errors = []
        if (item.type === 'select') {
            item.options.forEach((op, i) => {
                if (!op.value) {
                    _errors[i] = true
                }
            })
            setErrors(_errors)

            if (!item.options.length || _errors.length) {
                return setErrorData({
                    title: t('prompt'),
                    list: [t('flow.varOptionRequired')],
                });
            }
            const valiMap = {}
            if (item.options.find((op) => {
                if (valiMap[op.value]) return true
                valiMap[op.value] = true
            })) {
                return setErrorData({
                    title: t('prompt'),
                    list: [t('flow.optionRepeated')]
                });
            }
        }

        // 处理保存逻辑
        onSave({ ...item })
    };

    const handleDragEnd = (result) => {
        if (!result.destination) return;

        const newOptions = Array.from(item.options);
        const [movedOption] = newOptions.splice(result.source.index, 1);
        newOptions.splice(result.destination.index, 0, movedOption);

        setItem({ ...item, options: newOptions });
        setErrors([])
    };

    const handleChangeOptionValue = (value, index) => {
        const updatedItem = { ...item };
        updatedItem.options[index].value = value;
        setItem(updatedItem)
    }

    const VariablesName = <div>
        <label className='text-sm text-gray-500'>{t('flow.variableName')}：</label>
        <Input value={item.name} className='mt-2' onChange={(e) => setItem(prevItem => ({
            ...prevItem,
            name: e.target.value
        }))} />
    </div>

    return (<DialogContent className="sm:max-w-[425px]">
        <Tabs defaultValue={item.type}
            className="w-full"
            onValueChange={(t) => setItem(prevItem => ({
                ...prevItem,
                type: t
            }))} >
            <TabsList className="">
                <TabsTrigger value="text" className="roundedrounded-xl">{t('flow.text')}</TabsTrigger>
                <TabsTrigger value="select">{t('flow.dropdown')}</TabsTrigger>
            </TabsList>

            <TabsContent value="text">
                {VariablesName}
                <div>
                    <label className='text-sm text-gray-500'>{t('flow.maxLength')}：</label>
                    <Input value={item.maxLength} className='mt-2' onChange={(e) => setItem(prevItem => ({
                        ...prevItem,
                        maxLength: e.target.value
                    }))} />
                </div>
            </TabsContent>
            <TabsContent value="select" className='pb-10 px-2 max-h-80 overflow-y-auto scrollbar-hide'>
                {VariablesName}
                <label className='text-sm text-gray-500'>{t('flow.options')}：</label>
                <DragDropContext onDragEnd={handleDragEnd}>
                    <Droppable droppableId="list" direction="vertical" >
                        {(provide) => (
                            <div  {...provide.droppableProps} ref={provide.innerRef}>
                                {item.options.map((option, index) =>
                                    <Draggable key={'li' + option.key} draggableId={'li' + option.key} index={index}>
                                        {(provided, snapshot) => (
                                            <div className='flex mt-2 gap-2 select-none'
                                                ref={provided.innerRef} {...provided.draggableProps} {...provided.dragHandleProps}
                                                style={snapshot.isDragging ? {
                                                    ...provided.draggableProps.style, position: 'relative', left: 0, top: 0
                                                } : provided.draggableProps.style}>
                                                <Input value={option.value} className={errors[index] && 'border-red-400'} onChange={(e) => handleChangeOptionValue(e.target.value, index)} />
                                                <button onClick={() => {
                                                    setItem((old) => {
                                                        let newItem = cloneDeep(old);
                                                        newItem.options.splice(index, 1);
                                                        return newItem;
                                                    });
                                                    setErrors([])
                                                }}>
                                                    <X className={"h-4 w-4 hover:text-accent-foreground"} />
                                                </button>
                                                <button>
                                                    <ArrowDownUp className={"h-4 w-4 hover:text-accent-foreground"} />
                                                </button>
                                            </div>
                                        )}
                                    </Draggable>
                                )}
                                {/* {provide.placeholder} */}
                            </div>
                        )}
                    </Droppable>
                </DragDropContext>
                <button onClick={() =>
                    setItem(prevItem => ({
                        ...prevItem,
                        options: [...prevItem.options, { key: generateUUID(4), value: "" }]
                    }))
                }>
                    <Plus className={"h-4 w-4 mt-2 hover:text-accent-foreground"} />
                </button>
            </TabsContent>
        </Tabs>
        <DialogFooter>
            <Button className='px-8' variant='outline' size='sm' onClick={() => onClose(false)}>{t('cancel')}</Button>
            <Button className='px-8' onClick={handleSave} size='sm'>{t('save')}</Button>
        </DialogFooter>
        <div className='flex mt-4 justify-end gap-4'>
        </div>
    </DialogContent>
    );
};