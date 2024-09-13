import { DelIcon } from '@/components/bs-icons';
import { Button } from '@/components/bs-ui/button';
import { Input } from '@/components/bs-ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/bs-ui/radio';
import { generateUUID } from '@/components/bs-ui/utils';
import { useState } from 'react';
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';
import { useTranslation } from 'react-i18next';

const FileUploadSplitStrategy = ({ data: strategies, onChange: setStrategies }) => {
    const { t } = useTranslation('knowledge')
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
                { id: generateUUID(4), regex: customRegex, position }
            ]);
            setCustomRegex('');
        }
    };

    const handleRegexClick = (reg: string, position: string) => {
        setStrategies([
            ...strategies,
            { id: generateUUID(4), regex: reg, position }
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
                                    strategies.length !== 0 && strategies.map((strategy, index) => (
                                        <Draggable key={strategy.id} draggableId={strategy.id} index={index}>
                                            {(provided) => (
                                                <div
                                                    ref={provided.innerRef}
                                                    {...provided.draggableProps}
                                                    {...provided.dragHandleProps}
                                                    className="my-1 border rounded bg-accent text-sm"
                                                >
                                                    <div className='relative group h-full py-1 '>
                                                        {strategy.position === 'before' ? (
                                                            <span>✂️{strategy.regex}</span>
                                                        ) : (
                                                            <span>{strategy.regex}✂️</span>
                                                        )}
                                                        <DelIcon
                                                            onClick={() => setStrategies(strategies.filter((_, i) => i !== index))}
                                                            className='absolute right-1 top-0 hidden group-hover:block cursor-pointer' />
                                                    </div>
                                                </div>
                                            )}
                                        </Draggable>
                                    ))
                                }
                                {provided.placeholder}
                                <p className='text-xs text-gray-500'>{t('splitPriorityInfo')}</p>
                            </div>
                        )}
                    </Droppable>
                </DragDropContext>
            </div>

            <div className="flex flex-wrap mt-4 gap-2">
                <Button className="px-2 h-6" variant='secondary' onClick={() => handleRegexClick('\\n', 'after')}>\n✂️</Button>
                <Button className="px-2 h-6" variant="secondary" onClick={() => handleRegexClick('\\n\\n', 'after')}>\n\n✂️</Button>
                <Button className="px-2 h-6" variant='secondary' onClick={() => handleRegexClick('第.{1,3}章', 'before')}>{'✂️第.{1, 3}章'}</Button>
                <Button className="px-2 h-6" variant='secondary' onClick={() => handleRegexClick('第.{1,3}条', 'before')}>{'✂️第.{1, 3}条'}</Button>
                <Button className="px-2 h-6" variant='secondary' onClick={() => handleRegexClick('。', 'after')}>。✂️</Button>
                <Button className="px-2 h-6" variant='secondary' onClick={() => handleRegexClick('\\.', 'after')}>\.✂️</Button>
            </div>

            <div className="mt-4 text-sm flex flex-wrap items-center gap-2">
                <div className='flex items-center gap-1'>
                    <span>{t('in')}</span>
                    <Input
                        value={customRegex}
                        onChange={(e) => setCustomRegex(e.target.value)}
                        placeholder={t('enterRegex')}
                        className='w-40 py-0 h-6'
                    />
                    <RadioGroup value={position} onValueChange={setPosition} className="flex items-center">
                        <RadioGroupItem className="" value="before" />{t('before')}
                        <RadioGroupItem className="" value="after" />{t('after')}
                    </RadioGroup>
                </div>
                <Button onClick={handleAddCustomStrategy} className="h-6">
                    {t('addCustomRule')}
                </Button>
            </div>
        </div>
    );
};

export default FileUploadSplitStrategy;
