// components/ToolSelector.tsx
import { useState, useEffect, useRef, useCallback } from 'react';
import { DragDropContext, Droppable, Draggable } from 'react-beautiful-dnd';
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from '@/components/ui/accordion';
import { Plus, X, AlignJustify, User, Star, CpuIcon } from 'lucide-react';
import { SearchInput } from '../bs-ui/input';
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
  const MIN_HEIGHT = 360; // 设置最小高度
  const syncPanelHeights = useCallback(() => {
    if (leftPanelRef.current && rightContentRef.current) {
      const leftHeight = Math.max(leftPanelRef.current.scrollHeight, MIN_HEIGHT);
      const maxAllowedHeight = window.innerHeight * 0.8;
      const calculatedHeight = Math.min(leftHeight, maxAllowedHeight);

      // 应用高度到右侧容器
      rightContentRef.current.style.minHeight = `${MIN_HEIGHT}px`;
      rightContentRef.current.style.height = `${calculatedHeight}px`;

      // 设置左侧面板高度
      leftPanelRef.current.style.minHeight = `${MIN_HEIGHT}px`;
      leftPanelRef.current.style.height = `${calculatedHeight}px`
    }
  }, [MIN_HEIGHT]);

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

    let toolCategory = 'builtin';
    if (tool.is_preset === 0) {
      toolCategory = 'api';
    } else if (tool.is_preset === 2) {
      toolCategory = 'mcp';
    }

    setTargetCategory(toolCategory);
    setScrollToParentId(tool.id);

    // 使用setTimeout确保DOM更新完成后再执行滚动
    setTimeout(() => {
      if (activeToolTab !== toolCategory) {
        setActiveToolTab(toolCategory);
      } else {
        if (!expandedItems.includes(tool.id)) {
          setManuallyExpandedItems(prev => [...prev, tool.id]);
          // 等待展开动画完成
          setTimeout(() => scrollToTool(tool.id), 300);
        } else {
          scrollToTool(tool.id);
        }
      }
    }, 50);
  };
  const scrollToTool = useCallback((toolId: string) => {
    if (scrollTimeoutRef.current) {
      clearTimeout(scrollTimeoutRef.current);
    }

    scrollAttempts.current = 0;

    const tryScroll = () => {
      scrollAttempts.current++;
      const parentElement = document.getElementById(`tool-${toolId}`);
      const childElement = document.getElementById(`tool-child-${toolId}`);
      const container = rightContentRef.current;

      if (!container) {
        if (scrollAttempts.current < 10) {
          scrollTimeoutRef.current = setTimeout(tryScroll, 200);
        }
        return;
      }

      if (parentElement) {
        const parentRect = parentElement.getBoundingClientRect();
        const containerRect = container.getBoundingClientRect();

        // 判断元素是否完全可见
        const isFullyVisible = parentRect.top >= containerRect.top &&
          parentRect.bottom <= containerRect.bottom;

        if (!isFullyVisible) {
          // 对于长菜单项的特殊处理
          if (parentElement.offsetHeight > container.offsetHeight * 0.8) {
            // 如果菜单项高度超过容器高度的80%，滚动到顶部
            parentElement.scrollIntoView({
              behavior: 'smooth',
              block: 'start'
            });
          } else {
            // 正常大小的菜单项使用居中显示
            parentElement.scrollIntoView({
              behavior: 'smooth',
              block: 'center'
            });
          }
        }

        return;
      }

      if (scrollAttempts.current < 10) {
        scrollTimeoutRef.current = setTimeout(tryScroll, 200);
      }
    };

    tryScroll();
  }, []);
  useEffect(() => {
    const resizeObserver = new ResizeObserver(() => {
      syncPanelHeights();
    });

    if (leftPanelRef.current) {
      resizeObserver.observe(leftPanelRef.current);
    }

    return () => {
      resizeObserver.disconnect();
    };
  }, [syncPanelHeights]);
  useEffect(() => {
    if (targetCategory && activeToolTab === targetCategory && scrollToParentId) {
      if (!expandedItems.includes(scrollToParentId)) {
        setManuallyExpandedItems(prev => [...prev, scrollToParentId]);
        setTimeout(() => {
          scrollToTool(scrollToParentId);
          setTargetCategory(null);
        }, 300);
      } else {
        scrollToTool(scrollToParentId);
        setTargetCategory(null);
      }
    }
  }, [activeToolTab, targetCategory, scrollToParentId, expandedItems]);

  useEffect(() => {
    if (isExpanding && scrollToParentId) {
      setTimeout(() => {
        scrollToTool(scrollToParentId);
        setIsExpanding(false);
      }, 100);
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
        ref={leftPanelRef}
        className="w-1/3 flex border rounded-lg bg-white"
      >
        <div className="flex-1 p-4">
          <h3 className="text-[16px] font-medium">已选工具</h3>

          {selectedTools.length === 0 ? (
            <div className="mt-4 border-2 border-dashed border-gray-200 rounded-lg bg-gray-50 flex flex-col items-center justify-center py-6 px-4 text-center">
              <div className="mb-2">
                <Plus className="w-6 h-6 text-gray-400" />
              </div>
              <div className="text-sm font-medium text-gray-500 mb-1">
                暂未选择任何工具
              </div>
              <div className="text-xs text-gray-400">
                请在右侧全量工具中挑选工具
              </div>
            </div>
          ) : (
            <DragDropContext onDragEnd={handleDragEnd}>
              <Droppable droppableId="selectedTools">
                {(provided) => (
                  <div
                    {...provided.droppableProps}
                    ref={provided.innerRef}
                    className="space-y-2 flex-1 overflow-y-auto"
                    style={{ maxHeight: '300px' }}
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
          )}
        </div>
      </div>

      {/* 工具选择器 */}
      {(
        <div
          className="w-2/3 flex border rounded-lg bg-white overflow-hidden transition-all duration-300 ease-in-out"
          key={activeToolTab}
          ref={rightContentRef}
        >
          {/* 左侧分类栏 - 固定宽度 */}
          <div
            className="w-1/3 border-r bg-gray-50 flex flex-col">
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

            className="right-content w-2/3 flex flex-col h-full overflow-y-auto"
            style={{
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
                    <div className="flex items-center gap-2 py-3">
                      <AccordionTrigger className="p-0 w-4 hover:no-underline">
                      </AccordionTrigger>
                      <CustomCheckbox
                        state={getGroupState(tool)}
                        onChange={(checked) => toggleGroup(tool, checked)}
                      />
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <div className="flex flex-col min-w-0">
                              <p className="truncate max-w-[180px]">
                                {tool.name.split(new RegExp(`(${toolSearchTerm})`, 'gi')).map((part, i) => (
                                  part.toLowerCase() === toolSearchTerm.toLowerCase() ? (
                                    <span key={i} className="bg-yellow-200">{part}</span>
                                  ) : (
                                    <span key={i}>{part}</span>
                                  )
                                ))}
                              </p>
                              {/* 一级菜单描述 - 与二级菜单样式一致 */}
                              {tool.description && (
                                <p className="text-xs text-gray-500 truncate mt-1 max-w-[260px]">
                                  {tool.description}
                                </p>
                              )}
                            </div>
                          </TooltipTrigger>
                          <TooltipContent>
                            {tool.description && (
                              <p className='text-xs mt-1 max-w-[240px]'>
                                {tool.description}
                              </p>
                            )}
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
                                  <p className='max-w-[240px]'>{child.name}</p>
                                </TooltipContent>
                              </Tooltip>
                            </TooltipProvider>
                            {child.desc && (
                              <TooltipProvider>
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <p className="text-xs text-gray-500 truncate max-w-[260px] mt-1">{child.desc}</p>
                                  </TooltipTrigger>
                                  <TooltipContent>
                                    <p className='max-w-[240px]'>{child.desc}</p>
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