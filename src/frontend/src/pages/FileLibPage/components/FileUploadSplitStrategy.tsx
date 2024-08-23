import { Button } from '@/components/bs-ui/button';
import { Input } from '@/components/bs-ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/bs-ui/radio';
import { useState } from 'react';
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';

const FileUploadSplitStrategy = ({ data: strategies, onChange: setStrategies }) => {
    const [customRegex, setCustomRegex] = useState('');
    const [position, setPosition] = useState('after');

    const handleDragEnd = (result: any) => {
        if (!result.destination) return;

        const items = Array.from(strategies);
        const [reorderedItem] = items.splice(result.source.index, 1);
        items.splice(result.destination.index, 0, reorderedItem);

        setStrategies(items);
    };

    const handleAddCustomStrategy = () => {
        if (customRegex) {
            setStrategies([
                ...strategies,
                { id: `${strategies.length + 1}`, regex: customRegex, position }
            ]);
            setCustomRegex('');
        }
    };

    const handleRegexClick = (reg: string, position: string) => {
        setStrategies([
            ...strategies,
            { id: `${strategies.length + 1}`, regex: reg, position }
        ]);
    }

    return (
        <div>
            <div className='border border-dashed p-2 max-h-[20vh] overflow-y-auto'>
                <DragDropContext onDragEnd={handleDragEnd}>
                    <Droppable droppableId="strategies">
                        {(provided) => (
                            <div {...provided.droppableProps} ref={provided.innerRef}>
                                {
                                    strategies.length ? strategies.map((strategy, index) => (
                                        <Draggable key={strategy.id} draggableId={strategy.id} index={index}>
                                            {(provided) => (
                                                <div
                                                    ref={provided.innerRef}
                                                    {...provided.draggableProps}
                                                    {...provided.dragHandleProps}
                                                    className="py-1 my-1 border rounded bg-gray-100 text-sm"
                                                >
                                                    {strategy.position === 'before' ? (
                                                        <span>✂️{strategy.regex}</span>
                                                    ) : (
                                                        <span>{strategy.regex}✂️</span>
                                                    )}
                                                </div>
                                            )}
                                        </Draggable>
                                    ))
                                        : <p className='text-xs text-gray-500'>切分优先级按从高到低排序，可拖拽调整排序</p>
                                }
                                {provided.placeholder}
                            </div>
                        )}
                    </Droppable>
                </DragDropContext>
            </div>

            <div className="flex flex-wrap mt-4 gap-2">
                <Button className="px-2 h-6" variant='secondary' onClick={() => handleRegexClick('\\n', 'before')}>✂️\n</Button>
                <Button className="px-2 h-6" variant="secondary" onClick={() => handleRegexClick('\\n\\n', 'before')}>✂️\n\n</Button>
                <Button className="px-2 h-6" variant='secondary' onClick={() => handleRegexClick('第.{1,3}章', 'before')}>{'✂️第.{1, 3}章'}</Button>
                <Button className="px-2 h-6" variant='secondary' onClick={() => handleRegexClick('第.{1,3}条', 'before')}>{'✂️第.{1, 3}条'}</Button>
                <Button className="px-2 h-6" variant='secondary' onClick={() => handleRegexClick('。', 'after')}>。✂️</Button>
                <Button className="px-2 h-6" variant='secondary' onClick={() => handleRegexClick('\\.', 'after')}>\.✂️</Button>
            </div>

            <div className="mt-4 text-sm flex flex-wrap items-center gap-2">
                <div className='flex items-center gap-1'>
                    <span>在</span>
                    <Input value={customRegex} onChange={(e) => setCustomRegex(e.target.value)} placeholder="请输入正则表达式" className='w-40 py-0 h-6' />
                    <RadioGroup value={position} onValueChange={setPosition} className="flex items-center">
                        <RadioGroupItem className="" value="before" />前
                        <RadioGroupItem className="" value="after" />后
                    </RadioGroup>
                </div>
                <Button onClick={handleAddCustomStrategy} className="h-6">
                    添加自定义规则
                </Button>
            </div>
        </div>
    );
};

export default FileUploadSplitStrategy;
