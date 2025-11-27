import { DelIcon } from '@/components/bs-icons';
import { Button } from '@/components/bs-ui/button';
import { Input } from '@/components/bs-ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/bs-ui/radio';
import { generateUUID } from '@/components/bs-ui/utils';
import i18next from 'i18next';
import { useState, useEffect } from 'react';
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';
import { useTranslation } from 'react-i18next';

// Generate stable strategy ID (consistent with parent component)
const getStrategyId = (regexStr, position) => {
  // Simple hash function to ensure same content generates same ID
  let hash = 0;
  const str = `${regexStr}-${position}`;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash) + str.charCodeAt(i);
    hash = hash & hash; // Convert to 32bit integer
  }
  return `strategy-${Math.abs(hash)}`;
};

// Predefined rules mapping table
const PREDEFINED_RULES = {
  '\\n': {
    key: 'singleNewlineRule',
    display: {
      zh: '\\n✂️',
      en: '\\n✂️'
    },
    defaultPosition: 'after'
  },
  '\\n\\n': {
    key: 'doubleNewlineRule', 
    display: {
      zh: '\\n\\n✂️',
      en: '\\n\\n✂️'
    },
    defaultPosition: 'after'
  },
  '第.{1,3}章': {
    key: 'chapterRule',
    display: {
      zh: '✂️第.{1,3}章',
      en: '✂️Chapter.{1,3}'
    },
    defaultPosition: 'before'
  },
  '第.{1,3}条': {
    key: 'articleRule',
    display: {
      zh: '✂️第.{1,3}条',
      en: '✂️Article.{1,3}'
    },
    defaultPosition: 'before'
  },
  '。': {
    key: 'chinesePeriodRule',
    display: {
      zh: '。✂️',
      en: '。✂️'
    },
    defaultPosition: 'after'
  },
  '\\.': {
    key: 'englishPeriodRule',
    display: {
      zh: '\\.✂️',
      en: '\\.✂️'
    },
    defaultPosition: 'after'
  }
};

const FileUploadSplitStrategy = ({ data: strategies, onChange: setStrategies }) => {
  const { t } = useTranslation('knowledge')
  const [customRegex, setCustomRegex] = useState('');
  const [position, setPosition] = useState('after');
  const [currentLanguage, setCurrentLanguage] = useState(i18next.language);

  // Monitor language changes
  useEffect(() => {
    const handleLanguageChange = (lng) => {
      setCurrentLanguage(lng);
    };

    i18next.on('languageChanged', handleLanguageChange);
    
    return () => {
      i18next.off('languageChanged', handleLanguageChange);
    };
  }, []);

  // Data migration: One-time conversion of old data to new format
  useEffect(() => {
    const needsMigration = strategies.some(strategy => 
      strategy.rule && !strategy.ruleKey
    );

    if (needsMigration) {
      const migratedStrategies = strategies.map(strategy => {
        // If already in new format, return directly
        if (strategy.ruleKey) return strategy;

        // Process old format data
        const regex = strategy.regex;
        const predefinedRule = Object.entries(PREDEFINED_RULES).find(([pattern, rule]) => 
          pattern === regex
        );

        if (predefinedRule) {
          // Predefined rule
          return {
            ...strategy,
            ruleKey: predefinedRule[1].key,
            rule: undefined
          };
        } else if (strategy.rule && strategy.rule.startsWith('自定义规则: ')) {
          // Custom rule
          const customRegex = strategy.rule.replace('自定义规则: ', '');
          return {
            ...strategy,
            ruleKey: 'customRule',
            ruleParams: { regex: customRegex },
            rule: undefined
          };
        } else {
          // Unrecognized rule, keep as is
          return strategy;
        }
      });

      setStrategies(migratedStrategies);
    }
  }, [strategies, setStrategies]);

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

  const handleRegexClick = (reg) => {
    const predefinedRule = PREDEFINED_RULES[reg];
    if (!predefinedRule) return;

    const newStrategy = {
      id: getStrategyId(reg, predefinedRule.defaultPosition),
      regex: reg,
      position: predefinedRule.defaultPosition,
      ruleKey: predefinedRule.key
    };
    setStrategies([...strategies, newStrategy]);
  };

  const handleDelete = (id) => {
    setStrategies(strategies.filter(item => item.id !== id));
  };

  // Get strategy description text (real-time translation)
  const getStrategyDescription = (strategy) => {
    if (strategy.ruleKey === 'customRule') {
      return t(strategy.ruleKey, strategy.ruleParams || { regex: strategy.regex });
    }
    return t(strategy.ruleKey || '');
  };

  // Get button display text
  const getButtonDisplay = (regex) => {
    const rule = PREDEFINED_RULES[regex];
    if (!rule) return regex;
    
    return rule.display[currentLanguage] || rule.display.zh;
  };

  return (
    <div className='flex gap-6'>
      {/* Left drag area */}
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
                                <span className='ml-3 text-xs text-gray-500'>{getStrategyDescription(strategy)}</span>
                              </>
                            ) : (
                              <>
                                <span>{strategy.regex}✂️</span>
                                <span className='ml-3 text-xs text-gray-500'>{getStrategyDescription(strategy)}</span>
                              </>
                            )}
                            {/* Right gradient mask */}
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

                  {/* Add placeholders until 5 */}
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
          {Object.entries(PREDEFINED_RULES).map(([regex, rule]) => (
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