import { DelIcon } from '@/components/bs-icons';
import { Button } from '@/components/bs-ui/button';
import { Input } from '@/components/bs-ui/input';
import { generateUUID } from '@/components/bs-ui/utils';
import { GripVertical } from 'lucide-react';
import { useState } from 'react';
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';
import { useTranslation } from 'react-i18next';
export const ruleI18nMap = {
  '\\n': 'singleNewlineRule',
  '\\n\\n': 'doubleNewlineRule',
  '第.{1,3}章': 'chapterRule',
  '第.{1,3}条': 'articleRule',
  '。': 'chinesePeriodRule',
  '\\.': 'englishPeriodRule',
}

const predefinedRules = [
  { regexKey: '\\n', mode: 'after' },
  { regexKey: '\\n\\n', mode: 'after' },
  { regexKey: '第.{1,3}章', mode: 'before' },
  { regexKey: '第.{1,3}条', mode: 'before' },
  { regexKey: '。', mode: 'after' },
  { regexKey: '\\.', mode: 'after' }
];

const FileUploadSplitStrategy = ({ data: strategies, onChange: setStrategies }) => {
  const { t } = useTranslation('knowledge');
  const [customRegex, setCustomRegex] = useState('');
  const [position, setPosition] = useState('after');

  const handleDragEnd = (result) => {
    if (!result.destination) return;

    const items = Array.from(strategies);
    const [reorderedItem] = items.splice(result.source.index, 1);
    items.splice(result.destination.index, 0, reorderedItem);

    setStrategies(items);
  };

  const handleAddCustomStrategy = () => {
    if (customRegex.trim()) {
      const newStrategy = {
        id: generateUUID(6),
        regex: customRegex.trim(),
        position,
        rule: t('customRule'),
      };
      setStrategies([...strategies, newStrategy]);
      setCustomRegex('');
    }
  };

  const handleRegexClick = (regex, mode) => {
    const newStrategy = {
      id: generateUUID(6),
      regex: t(`predefinedRules.${ruleI18nMap[regex]}.label`),
      position: mode,
      rule: t(`predefinedRules.${ruleI18nMap[regex]}.desc`),
    };
    setStrategies([...strategies, newStrategy]);
  };

  const handleDelete = (id) => {
    setStrategies(strategies.filter(item => item.id !== id));
  };

  return (
    <div className='grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.08fr)]'>
      <div className="flex min-w-0 flex-col gap-5">
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-[#374151]">{t('recommendedRules')}</h3>
          <div className="flex flex-wrap gap-2">
            {predefinedRules.map((rule, index) => {
              const regexDisplay = t(`predefinedRules.${ruleI18nMap[rule.regexKey]}.label`);
              return (
                <Button
                  key={index}
                  className="h-6 rounded-[7px] bg-[#f1f5f9] px-2.5 text-[#0f172a] shadow-sm hover:bg-[#e7edf8]"
                  variant="secondary"
                  onClick={() => handleRegexClick(rule.regexKey, rule.mode)}
                >
                  {rule.mode === 'before' ? `✂️${regexDisplay}` : `${regexDisplay}✂️`}
                </Button>
              );
            })}
          </div>
        </div>

        <div className="space-y-3">
          <h3 className="text-sm font-medium text-[#374151]">{t('addCustomRule')}</h3>
          <div className="flex items-center gap-3">
            <div className="flex min-w-0 flex-1 items-center gap-1">
              <span className="shrink-0 text-sm text-[#0f172a]">{t('in')}</span>
              <Input
                value={customRegex}
                onChange={(e) => setCustomRegex(e.target.value)}
                placeholder={t('enterRegex')}
                className='h-8 flex-1 border-[#ebecf0] bg-white'
              />
              <div className="inline-flex shrink-0 items-center rounded-md bg-[#f8f8f8] p-1">
                {['before', 'after'].map((item) => (
                  <button
                    key={item}
                    type="button"
                    className={`rounded-[4px] px-3 py-1 text-sm transition-colors ${position === item ? 'bg-primary/15 font-medium text-primary' : 'text-[#818181]'}`}
                    onClick={() => setPosition(item)}
                  >
                    {item === 'before' ? t('before') : t('after')}
                  </button>
                ))}
              </div>
              <span className="shrink-0 text-sm text-[#0f172a]">{t('split')}</span>
            </div>
            <Button onClick={handleAddCustomStrategy} className="h-8 shrink-0 rounded-md border-[#ebecf0] bg-white px-4 text-[#070038]" variant="outline">
              {t('add')}
            </Button>
          </div>
        </div>
      </div>

      <div className='min-w-0'>
        <div className="mb-3 flex flex-wrap items-center gap-2 leading-none">
          <h3 className="text-sm font-medium text-[#374151]">{t('addedRules')}</h3>
          <p className='text-sm text-[#999]'>{t('splitPriorityInfo')}</p>
        </div>
        <div className='max-h-[12.5rem] select-none overflow-y-auto pr-1'>
          <DragDropContext onDragEnd={handleDragEnd}>
            <Droppable droppableId="strategies">
              {(provided) => (
                <div {...provided.droppableProps} ref={provided.innerRef}>
                  {strategies.map((strategy, index) => (
                    <Draggable key={strategy.id} draggableId={strategy.id} index={index}>
                      {(provided) => (
                        <div
                          ref={provided.innerRef}
                          {...provided.draggableProps}
                          className="group my-1 flex items-center gap-2 rounded-[4px] border border-[#e4e8ee] bg-[#f2f5f8] px-2 py-1 text-sm"
                        >
                          <div
                            {...provided.dragHandleProps}
                            className="flex h-5 w-5 shrink-0 cursor-grab items-center justify-center text-[#94a3b8] active:cursor-grabbing"
                          >
                            <GripVertical className="size-4" />
                          </div>
                          <div className='flex min-w-0 flex-1 items-center gap-3 overflow-hidden'>
                            <span className="shrink-0 text-sm text-[#0f172a]">
                              {strategy.position === 'before' ? `✂️${strategy.regex}` : `${strategy.regex}✂️`}
                            </span>
                            <span className='min-w-0 truncate text-xs text-[#4e5969]'>{strategy.rule}</span>
                          </div>
                          <div className="flex items-center">
                            <DelIcon
                              onClick={() => handleDelete(strategy.id)}
                              className='cursor-pointer text-[#94a3b8] opacity-0 transition-opacity group-hover:opacity-100'
                            />
                          </div>
                        </div>
                      )}
                    </Draggable>
                  ))}

                  {strategies.length < 5 && (
                    Array(5 - strategies.length).fill(null).map((_, index) => (
                      <div
                        key={`placeholder-${index}`}
                        className="my-1 h-8 rounded-[4px] bg-[#f3f4f6] opacity-60"
                      />
                    ))
                  )}
                  {provided.placeholder}
                </div>
              )}
            </Droppable>
          </DragDropContext>
        </div>
      </div>
    </div>
  );
};

export default FileUploadSplitStrategy;
