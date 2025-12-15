import { DelIcon } from '@/components/bs-icons';
import { Button } from '@/components/bs-ui/button';
import { Input } from '@/components/bs-ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/bs-ui/radio';
import { generateUUID } from '@/components/bs-ui/utils';
import i18next, { use } from 'i18next';
import { useMemo, useState } from 'react';
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
    // 根据regex获取对应的规则key
    const newStrategy = {
      id: generateUUID(6),
      regex:t(`predefinedRules.${ruleI18nMap[regex]}.label`),
      position: mode,
      rule: t(`predefinedRules.${ruleI18nMap[regex]}.desc`),
    };
    setStrategies([...strategies, newStrategy]);
  };

  const handleDelete = (id) => {
    setStrategies(strategies.filter(item => item.id !== id));
  };

const [predefinedRules] = useState([
    { regexKey:  '\\n', mode: 'after' },
    { regexKey:'\\n\\n', mode: 'after' },
    { regexKey:  '第.{1,3}章', mode: 'before' },
    { regexKey: '第.{1,3}条', mode: 'before' },
    { regexKey: '。', mode: 'after' },
    { regexKey: '\\.', mode: 'after' }

  ]);

  return (
    <div className='flex gap-6'>
      {/* 左侧拖拽区域 */}
      <div className='flex-1'>
        <div className='py-2 px-0 pr-1 overflow-y-auto max-h-[11.5rem] select-none'>
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
                          {...provided.dragHandleProps}
                          className="my-1 border rounded bg-accent text-sm h-8"
                        >
                          <div className='relative group h-full py-1 px-2 whitespace-nowrap overflow-hidden max-w-96'>
                            {strategy.position === 'before' ? (
                              <>
                                <span>✂️{strategy.regex}</span>
                                <span className='ml-3 text-xs text-gray-500'>{strategy.rule}</span>
                              </>
                            ) : (
                              <>
                                <span>{strategy.regex}✂️</span>
                                <span className='ml-3 text-xs text-gray-500'>{strategy.rule}</span>
                              </>
                            )}
                            {/* 右侧渐变遮罩 */}
                            <div className="absolute inset-y-0 right-0 w-16 bg-gradient-to-l from-accent to-transparent pointer-events-none"></div>
                            <DelIcon
                              onClick={() => handleDelete(strategy.id)}
                              className='absolute right-1 top-0 hidden group-hover:block cursor-pointer'
                            />
                          </div>
                        </div>
                      )}
                    </Draggable>
                  ))}

                  {/* 添加占位符直到5个 */}
                  {strategies.length < 5 && (
                    Array(5 - strategies.length).fill(null).map((_, index) => (
                      <div
                        key={`placeholder-${index}`}
                        className="my-1 border rounded bg-gray-100 text-sm opacity-50 h-8"
                      >
                        <div className='relative group h-full py-1 px-2'>
                          <span className="text-gray-400"> </span>
                        </div>
                      </div>
                    ))
                  )}
                  {provided.placeholder}
                </div>
              )}
            </Droppable>
          </DragDropContext>
        </div>
        <p className='text-xs text-gray-500 pt-1'>{t('splitPriorityInfo')}</p>
      </div>

      <div className="flex-1 flex flex-col gap-3 px-1"> 
        <h3 className="text-sm text-left font-medium text-gray-700">{t('universalRules')}:</h3>
        <div className="flex flex-wrap gap-2">
          {predefinedRules.map((rule, index) => {
            const regexDisplay = t(`predefinedRules.${ruleI18nMap[rule.regexKey]}.label`);
            return (
              <Button
                key={index}
                className="px-2 h-6"
                variant="secondary"
                onClick={() => handleRegexClick(rule.regexKey, rule.mode)}
              >
                {rule.mode === 'before' ? `✂️${regexDisplay}` : `${regexDisplay}✂️`}
              </Button>
            );
          })}
        </div>
        
        <h3 className="text-sm text-left font-medium text-gray-700"> {t('addCustomRule')}:</h3>
        <div className="text-sm flex flex-wrap items-center gap-2">
          <div className='flex items-center gap-1 w-full'>
            <span>{t('in')}</span>
            <Input
              value={customRegex}
              onChange={(e) => setCustomRegex(e.target.value)}
              placeholder={t('enterRegex')}
              className='flex-1 py-0 h-6' 
            />
          </div>
        </div>

        <RadioGroup 
          value={position} 
          onValueChange={setPosition} 
          className="flex items-center flex-wrap text-sm gap-2" 
        >
          <div className="flex items-center gap-1"> 
            <RadioGroupItem value="before" id={`radio-before-${Date.now()}`} />
            <label htmlFor={`radio-before-${Date.now()}`} className="cursor-pointer">
              {t('before')}
            </label>
          </div>
          <div className="flex items-center gap-1">
            <RadioGroupItem value="after" id={`radio-after-${Date.now()}`} />
            <label htmlFor={`radio-after-${Date.now()}`} className="cursor-pointer">
              {t('after')}
            </label>
          </div>
          <span className="ml-1">{t('split')}</span> 
        </RadioGroup>

        <div className="flex justify-end mt-2"> 
          <Button onClick={handleAddCustomStrategy} className="h-6 px-3"> 
            {t('add')}
          </Button>
        </div>
      </div>
    </div>
  );
};

export default FileUploadSplitStrategy;