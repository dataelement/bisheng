// components/ToolSelector.tsx
import { useState, useEffect, useRef, useCallback } from 'react';
import { DragDropContext, Droppable, Draggable } from 'react-beautiful-dnd';
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from '@/components/ui/accordion';
import { Plus, X, AlignJustify, User, Star, CpuIcon } from 'lucide-react';
import { SearchInput } from '../bs-ui/input';
import { Button } from '../bs-ui/button';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../bs-ui/tooltip';
import { Check, Minus } from "lucide-react";
import { LoadIcon } from '../bs-icons/loading';

type CheckboxState = 'checked' | 'unchecked' | 'indeterminate';

const ToolSelector = ({
  selectedTools,
  toggleTool,
  removeTool,
  isToolSelected,
  handleDragEnd,
  showToolSelector,
  setShowToolSelector,
  toolsData,
  activeToolTab,
  setActiveToolTab,
  toolSearchTerm,
  setToolSearchTerm,
  loading,
  filteredTools,
  expandedItems,
  setManuallyExpandedItems,
  toggleGroup,
}) => {
  const [scrollToParentId, setScrollToParentId] = useState<string | null>(null);
  const [isExpanding, setIsExpanding] = useState(false);
  const [targetCategory, setTargetCategory] = useState<string | null>(null);
  const scrollAttempts = useRef(0);
  const scrollTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const leftPanelRef = useRef<HTMLDivElement>(null);
  const rightContentRef = useRef<HTMLDivElement>(null);

  const [rightMaxHeight, setRightMaxHeight] = useState<number | null>(null);

  const syncPanelHeights = useCallback(() => {
    if (leftPanelRef.current && rightContentRef.current) {
      const leftHeight = leftPanelRef.current.scrollHeight;
      const rightContentHeight = rightContentRef.current.scrollHeight;

      // 如果右侧内容小于左侧高度，则不限制高度
      if (rightContentHeight < leftHeight) {
        setRightMaxHeight(null);
      } else {
        setRightMaxHeight(leftHeight);
      }
    }
  }, []);
  // 增加对 requestIdleCallback 的判断和使用
  useEffect(() => {
    if (showToolSelector && filteredTools.length > 0) {
      const handle = requestIdleCallback(() => {
        syncPanelHeights();
      }, { timeout: 1000 });
      return () => cancelIdleCallback(handle);
    }
  }, [showToolSelector, filteredTools, syncPanelHeights]);
  useEffect(() => {
    if (showToolSelector) {
      const id = requestAnimationFrame(() => {
        syncPanelHeights();
      });
      return () => cancelAnimationFrame(id);
    }
  }, [showToolSelector, syncPanelHeights]);
  useEffect(() => {
    syncPanelHeights();
  }, [syncPanelHeights, selectedTools, filteredTools, expandedItems, showToolSelector]);

  const handleSelectedToolClick = (tool) => {
    setShowToolSelector(true);
    console.log(tool);

    let toolCategory = 'builtin';
    if (tool.is_preset === 0) {
      toolCategory = 'api';
    } else if (tool.is_preset === 2) {
      toolCategory = 'mcp';
    }
    console.log(toolCategory, 123);

    setTargetCategory(toolCategory);
    setScrollToParentId(tool.id);

    if (activeToolTab !== toolCategory) {
      setActiveToolTab(toolCategory);
    } else {
      scrollToTool(tool.id);
    }

    if (!expandedItems.includes(tool.id)) {
      setIsExpanding(true);
      setManuallyExpandedItems([...expandedItems, tool.id]);
    } else {
      scrollToTool(tool.id);
    }
  };
  const scrollToTool = useCallback((toolId: string) => {
    if (scrollTimeoutRef.current) {
      clearTimeout(scrollTimeoutRef.current);
    }

    scrollAttempts.current = 0;

    const tryScroll = () => {
      scrollAttempts.current++;
      const element = document.getElementById(`tool-${toolId}`);

      if (element && rightContentRef.current) {
        // 使用ref获取容器而不是querySelector
        const container = rightContentRef.current;

        // 计算元素相对于容器的位置
        const elementTop = element.offsetTop;
        const containerTop = container.offsetTop;
        const scrollPosition = elementTop - containerTop - 20; // 减去20px作为缓冲

        // 平滑滚动到目标位置
        container.scrollTo({
          top: scrollPosition,
          behavior: 'smooth'
        });

        // 高亮显示目标元素
        element.classList.add('bg-blue-50');
        setTimeout(() => {
          element.classList.remove('bg-blue-50');
        }, 2000);
      } else if (scrollAttempts.current < 5) {
        // 如果元素未找到，重试最多5次
        scrollTimeoutRef.current = setTimeout(tryScroll, 200);
      }
    };

    // 初始尝试
    scrollTimeoutRef.current = setTimeout(tryScroll, 100);
  }, []);

  useEffect(() => {
    if (targetCategory && activeToolTab === targetCategory && scrollToParentId) {
      scrollToTool(scrollToParentId);
      setTargetCategory(null);
    }
  }, [activeToolTab, targetCategory]);

  useEffect(() => {
    if (isExpanding && scrollToParentId) {
      setTimeout(() => {
        scrollToTool(scrollToParentId);
        setIsExpanding(false);
      }, 500);
    }
  }, [isExpanding, scrollToParentId]);

  useEffect(() => {
    return () => {
      if (scrollTimeoutRef.current) {
        clearTimeout(scrollTimeoutRef.current);
      }
    };
  }, []);

  const getGroupState = (group): CheckboxState => {
    const parent = selectedTools.find(t => t.id === group.id);
    if (!parent) return 'unchecked';
    if (parent.children?.length === group.children.length) return 'checked';
    return 'indeterminate';
  };

  const CustomCheckbox = ({ state, onChange }) => (
    <button
      type="button"
      className={`w-4 h-4 border rounded flex items-center justify-center 
        ${state !== 'unchecked' ? 'bg-primary border-primary' : 'border-gray-300'}`}
      style={{ color: 'white' }}
      onClick={() => onChange(state !== 'checked')}
    >
      {state === 'checked' && <Check className="w-3 h-3 text-white" />}
      {state === 'indeterminate' && <Minus className="w-3 h-3 text-white" />}
    </button>
  );

  return (
    <div className="flex gap-4">
      {/* 已选工具面板 */}
      <div
        className="w-1/3 flex border rounded-lg bg-white">
        <div className="flex-1 p-4">
          <h3 className="text-sm font-medium">已选工具</h3>
          {selectedTools.length === 0 && (
            <button
              onClick={() => { setShowToolSelector(true), setActiveToolTab('builtin') }}
              className="mt-2 px-3 py-1 text-sm border border-gray-300 rounded text-gray-600 hover:border-gray-400 hover:text-gray-800 transition-colors"
            >
              <Plus className="inline w-4 h-4 mr-1" />
              添加更多工具
            </button>
          )}

          <DragDropContext onDragEnd={handleDragEnd}>
            <Droppable droppableId="selectedTools">
              {(provided) => (
                <div
                  {...provided.droppableProps}
                  ref={provided.innerRef}
                  className="space-y-2 min-h-[100px] p-2 rounded-lg"
                >
                  {selectedTools.map((tool, index) => (
                    <Draggable key={tool.id.toString()} draggableId={tool.id.toString()} index={index}>
                      {(provided, snapshot) => (
                        <div
                          ref={provided.innerRef}
                          {...provided.draggableProps}
                          {...provided.dragHandleProps}
                          className={`flex items-center justify-between p-3 py-2 rounded-lg ${snapshot.isDragging ? 'bg-blue-50 shadow-md' : 'bg-white border'
                            }`}
                          onClick={() => handleSelectedToolClick(tool)}
                        >
                          <div className="flex items-center">
                            <AlignJustify className="w-4 h-4 mr-2 text-gray-400" />
                            <TooltipProvider>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <span className="truncate max-w-[120px]">{tool.name}</span>
                                </TooltipTrigger>
                                <TooltipContent>
                                  <p>{tool.name}</p>
                                </TooltipContent>
                              </Tooltip>
                            </TooltipProvider>
                          </div>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              removeTool(index);
                            }}
                            className="text-red-500 hover:text-red-700 ml-2"
                          >
                            <X className="w-4 h-4" />
                          </button>
                        </div>
                      )}
                    </Draggable>
                  ))}
                  {provided.placeholder}
                </div>
              )}
            </Droppable>
          </DragDropContext>

          {selectedTools.length > 0 && (
            <Button
              variant='outline'
              onClick={() => { setShowToolSelector(true), setActiveToolTab('builtin') }}
            >
              <Plus className="inline w-4 h-4 mr-1" />
              添加更多工具
            </Button>
          )}
        </div>
      </div>

      {/* 工具选择器 */}
      {showToolSelector && (
        <div
          className="w-2/3 flex border rounded-lg bg-white overflow-hidden transition-all duration-300 ease-in-out"
          key={activeToolTab}
        >
          {/* 左侧分类栏 - 固定宽度 */}
          <div
            ref={leftPanelRef}
            className="w-1/3 border-r bg-gray-50 flex flex-col h-full">
            <div className="p-2 border-b">
              <h3 className="font-medium">全量工具</h3>
            </div>
            <div className="relative p-2 border-b">
              <SearchInput
                placeholder="搜索工具..."
                value={toolSearchTerm}
                onChange={(e) => setToolSearchTerm(e.target.value)}
                onClear={() => setToolSearchTerm('')}
              />
            </div>

            <div className="flex-1 overflow-y-auto p-2">
              <div className="space-y-1">
                <button
                  className={`flex items-center w-full text-left p-2 rounded ${activeToolTab === 'builtin' ? 'bg-blue-100 text-blue-600' : 'hover:bg-gray-100'}`}
                  onClick={() => setActiveToolTab('builtin')}
                >
                  <User className="w-4 h-4 mr-2" />
                  内置工具
                </button>
                <button
                  className={`flex items-center w-full text-left p-2 rounded ${activeToolTab === 'api' ? 'bg-blue-100 text-blue-600' : 'hover:bg-gray-100'}`}
                  onClick={() => setActiveToolTab('api')}
                >
                  <Star className="w-4 h-4 mr-2" />
                  API工具
                </button>
                <button
                  className={`flex items-center w-full text-left p-2 rounded ${activeToolTab === 'mcp' ? 'bg-blue-100 text-blue-600' : 'hover:bg-gray-100'}`}
                  onClick={() => setActiveToolTab('mcp')}
                >
                  <CpuIcon className="w-4 h-4 mr-2" />
                  MCP工具
                </button>
              </div>
            </div>
          </div>

          <div
            ref={rightContentRef}
            className="right-content w-2/3 flex flex-col"
            style={{
              maxHeight: rightMaxHeight ? `${rightMaxHeight}px` : undefined,
              overflowY: rightMaxHeight ? 'auto' : 'visible',
              transition: 'max-height 0.3s ease-out',
            }}
          >
            {loading ? (
              <div className="flex justify-center items-center h-full">
                <LoadIcon className="animate-spin" />
              </div>
            ) : filteredTools.length > 0 ? (
              <Accordion
                type="multiple"
                className="w-full p-4"
                value={expandedItems}
                onValueChange={(values) => {
                  if (!toolSearchTerm) {
                    setManuallyExpandedItems(values);
                  }
                }}
              >
                {filteredTools.map((tool) => (
                  <AccordionItem
                    key={tool.id}
                    value={tool.id}
                    id={`tool-${tool.id}`}
                    className={expandedItems.includes(tool.id) ? 'bg-gray-50' : ''}
                  >
                    <div className="flex items-center gap-2">
                      <AccordionTrigger className="p-0 w-4 hover:no-underline">
                      </AccordionTrigger>
                      <CustomCheckbox
                        state={getGroupState(tool)}
                        onChange={(checked) => toggleGroup(tool, checked)}
                      />
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span className="truncate max-w-[180px] py-2">
                              {tool.name.split(new RegExp(`(${toolSearchTerm})`, 'gi')).map((part, i) => (
                                part.toLowerCase() === toolSearchTerm.toLowerCase() ? (
                                  <span key={i} className="bg-yellow-200">{part}</span>
                                ) : (
                                  <span key={i}>{part}</span>
                                )
                              ))}
                            </span>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>{tool.name}</p>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </div>

                    <AccordionContent>
                      {tool.children?.map(child => (
                        <div
                          key={child.id}
                          id={`tool-child-${child.id}`}
                          className="flex items-center gap-2 ml-10 p-2 hover:bg-gray-50 cursor-pointer"
                          onClick={() => toggleTool(tool, child)}
                        >
                          <div className={`w-4 h-4 border rounded flex items-center justify-center 
                            ${isToolSelected(tool.id, child.id) ? 'bg-primary border-primary' : 'border-gray-300'}`}>
                            {isToolSelected(tool.id, child.id) && <Check className="w-3 h-3" style={{ color: 'white' }} />}
                          </div>
                          <div className="min-w-0">
                            <TooltipProvider>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <p className="truncate max-w-[180px]">
                                    {child.name.split(new RegExp(`(${toolSearchTerm})`, 'gi')).map((part, i) => (
                                      part.toLowerCase() === toolSearchTerm.toLowerCase() ? (
                                        <span key={i} className="bg-yellow-200">{part}</span>
                                      ) : (
                                        <span key={i}>{part}</span>
                                      )
                                    ))}
                                  </p>
                                </TooltipTrigger>
                                <TooltipContent>
                                  <p>{child.name}</p>
                                </TooltipContent>
                              </Tooltip>
                            </TooltipProvider>
                            {child.desc && (
                              <TooltipProvider>
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <p className="text-xs text-gray-500 truncate max-w-[260px]">{child.desc}</p>
                                  </TooltipTrigger>
                                  <TooltipContent>
                                    <p>{child.desc}</p>
                                  </TooltipContent>
                                </Tooltip>
                              </TooltipProvider>
                            )}
                          </div>
                        </div>
                      ))}
                    </AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            ) : (
              <div className="text-center text-sm text-gray-500 py-4">
                未找到相关工具
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default ToolSelector;