import { DelIcon } from '@/components/bs-icons';
import { Button } from '@/components/bs-ui/button';
import { Input } from '@/components/bs-ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/bs-ui/radio';
import { generateUUID } from '@/components/bs-ui/utils';
import i18next from 'i18next';
import { useState } from 'react';
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';
import { useTranslation } from 'react-i18next';

// 生成稳定的策略ID（与父组件保持一致）
const getStrategyId = (regexStr, position) => {
  // 简单的哈希函数，确保相同内容生成相同ID
  let hash = 0;
  const str = `${regexStr}-${position}`;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash) + str.charCodeAt(i);
    hash = hash & hash; // Convert to 32bit integer
  }
  return `strategy-${Math.abs(hash)}`;
};

const FileUploadSplitStrategy = ({ data: strategies, onChange: setStrategies }) => {
  const { t } = useTranslation('knowledge')
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
        id: getStrategyId(customRegex.trim(), position),
        regex: customRegex.trim(),
        position,
        rule: `自定义规则: ${customRegex.trim()}`
      };
      setStrategies([...strategies, newStrategy]);
      setCustomRegex('');
      // 检查是否已存在相同策略
      // const exists = strategies.some(s => s.id === newStrategy.id);
      // if (!exists) {
      //   setStrategies([...strategies, newStrategy]);
      //   setCustomRegex('');
      // }
    }
  };

  const handleRegexClick = (reg, pos, rule) => {
    const newStrategy = {
      id: getStrategyId(reg, pos),
      regex: reg,
      position: pos,
      rule
    };
    setStrategies([...strategies, newStrategy]);
    // 检查是否已存在相同策略
    // const exists = strategies.some(s => s.id === newStrategy.id);
    // if (!exists) {
    //   setStrategies([...strategies, newStrategy]);
    // }
  };

  const handleDelete = (id) => {
    setStrategies(strategies.filter(item => item.id !== id));
  };

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
      
      <div className="relative flex-1 flex flex-col gap-4">
        <h3 className="text-sm text-left font-medium text-gray-700">{t('universalRules')}:</h3>
        <div className="flex flex-wrap gap-2">
          <Button className="px-2 h-6" variant='secondary' onClick={() => handleRegexClick('\\n', 'after', '单换行后切分，用于分隔普通换行')}>\n✂️</Button>
          <Button className="px-2 h-6" variant="secondary" onClick={() => handleRegexClick('\\n\\n', 'after', '双换行后切分，用于分隔段落')}>\n\n✂️</Button>
          {i18next.language === 'zh' && <>
            <Button className="px-2 h-6" variant='secondary' onClick={() => handleRegexClick('第.{1,3}章', 'before', '"第X章"前切分，切分章节等')}>{'✂️第.{1,3}章'}</Button>
            <Button className="px-2 h-6" variant='secondary' onClick={() => handleRegexClick('第.{1,3}条', 'before', '"第X条"前切分，切分条目等')}>{'✂️第.{1,3}条'}</Button>
          </>}
          <Button className="px-2 h-6" variant='secondary' onClick={() => handleRegexClick('。', 'after', '中文句号后切分，中文断句')}>。✂️</Button>
          <Button className="px-2 h-6" variant='secondary' onClick={() => handleRegexClick('\\.', 'after', '英文句号后切分，英文断句')}>\.✂️</Button>
        </div>
        
        <h3 className="text-sm text-left font-medium text-gray-700"> {t('addCustomRule')}:</h3>
        <div className="text-sm flex flex-wrap items-center gap-2">
          <div className='flex items-center gap-1'>
            <span>{t('in')}</span>
            <Input
              value={customRegex}
              onChange={(e) => setCustomRegex(e.target.value)}
              placeholder={t('enterRegex')}
              className='w-full py-0 h-6'
            />
          </div>
        </div>
        
        <RadioGroup value={position} onValueChange={setPosition} className="flex items-center text-sm">
          <RadioGroupItem value="before" />{t('before')}
          <RadioGroupItem value="after" />{t('after')}
          <span>切分</span>
        </RadioGroup>
        
        <div className="flex justify-end absolute right-0 bottom-0">
          <Button onClick={handleAddCustomStrategy} className="h-6">
            {t('add')}
          </Button>
        </div>
      </div>
    </div>
  );
};

export default FileUploadSplitStrategy;