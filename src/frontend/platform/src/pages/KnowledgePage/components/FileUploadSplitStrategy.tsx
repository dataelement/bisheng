import { DelIcon } from '@/components/bs-icons';
import { Button } from '@/components/bs-ui/button';
import { Input } from '@/components/bs-ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/bs-ui/radio';
import { useState, useEffect, useMemo } from 'react';
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';
import { useTranslation } from 'react-i18next';

// Generate stable strategy ID
const getStrategyId = (regexStr, position) => {
  let hash = 0;
  const str = `${regexStr}-${position}`;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash) + str.charCodeAt(i);
    hash = hash & hash;
  }
  return `strategy-${Math.abs(hash)}`;
};

const FileUploadSplitStrategy = ({ data: strategies, onChange: setStrategies }) => {
  const { t } = useTranslation('knowledge');
  const [customRegex, setCustomRegex] = useState('');
  const [position, setPosition] = useState('after');

  const PREDEFINED_RULES_CONFIG = useMemo(() => {
    return {
      '\\n': {
        key: 'singleNewlineRule',
        defaultPosition: 'after'
      },
      '\\n\\n': {
        key: 'doubleNewlineRule', 
        defaultPosition: 'after'
      },

      [t('predefinedRules.chapterRule')]: {
        key: 'chapterRule',
        defaultPosition: 'before'
      },

      [t('predefinedRules.articleRule')]: {
        key: 'articleRule',
        defaultPosition: 'before'
      },

      '。': {
        key: 'chinesePeriodRule',
        defaultPosition: 'after'
      },
      '\\.': {
        key: 'englishPeriodRule',
        defaultPosition: 'after'
      }
    };
  }, [t]);

  const getPredefinedRuleDisplay = (ruleKey) => {
    return t(`predefinedRules.${ruleKey}`, { defaultValue: ruleKey });
  };

  const getRuleDescription = (ruleKey, ruleParams = {}) => {
    return t(`${ruleKey}`, ruleParams);
  };

  useEffect(() => {
    const needsMigration = strategies.some(strategy => 
      strategy.rule && !strategy.ruleKey
    );

    if (needsMigration) {
      const migratedStrategies = strategies.map(strategy => {
        if (strategy.ruleKey) return strategy;

        const regex = strategy.regex;
        const predefinedRule = Object.entries(PREDEFINED_RULES_CONFIG).find(([pattern, rule]) => 
          pattern === regex
        );

        if (predefinedRule) {
          return {
            ...strategy,
            ruleKey: predefinedRule[1].key,
            rule: undefined
          };
        } else if (strategy.rule && strategy.rule.startsWith('自定义规则: ')) {
          const customRegex = strategy.rule.replace('自定义规则: ', '');
          return {
            ...strategy,
            ruleKey: 'customRule',
            ruleParams: { regex: customRegex },
            rule: undefined
          };
        } else {
          return strategy;
        }
      });

      setStrategies(migratedStrategies);
    }
  }, [strategies, setStrategies, PREDEFINED_RULES_CONFIG]);

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
        ruleKey: 'customRule',
        ruleParams: { regex: customRegex.trim() }
      };
      setStrategies([...strategies, newStrategy]);
      setCustomRegex('');
    }
  };

  const handleRegexClick = (regex) => {
    const predefinedRule = PREDEFINED_RULES_CONFIG[regex];
    if (!predefinedRule) return;

    const newStrategy = {
      id: getStrategyId(regex, predefinedRule.defaultPosition),
      regex: regex,
      position: predefinedRule.defaultPosition,
      ruleKey: predefinedRule.key
    };
    setStrategies([...strategies, newStrategy]);
  };

  const handleDelete = (id) => {
    setStrategies(strategies.filter(item => item.id !== id));
  };

  const getStrategyDescription = (strategy) => {
    return getRuleDescription(strategy.ruleKey, strategy.ruleParams || { regex: strategy.regex });
  };

  const getButtonDisplay = (regex) => {
    const ruleConfig = PREDEFINED_RULES_CONFIG[regex];
    if (!ruleConfig) return regex;
    
    return getPredefinedRuleDisplay(ruleConfig.key);
  };

  return (
    <div className='flex gap-6'>
      {/* Left drag area */}
      <div className='flex-1 max-w-[50%]'>
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
                                <span className='ml-3 text-xs text-gray-500'>{getStrategyDescription(strategy)}</span>
                              </>
                            ) : (
                              <>
                                <span>{strategy.regex}✂️</span>
                                <span className='ml-3 text-xs text-gray-500'>{getStrategyDescription(strategy)}</span>
                              </>
                            )}
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
          {Object.keys(PREDEFINED_RULES_CONFIG).map((regex) => (
            <Button 
              key={regex}
              className="px-2 h-6" 
              variant='secondary' 
              onClick={() => handleRegexClick(regex)}
            >
              {getButtonDisplay(regex)}
            </Button>
          ))}
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
          <span>{t('split')}</span>
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