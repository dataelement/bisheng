import { useMemo, useState } from 'react';
import ToolSelector from './ToolSelector';

export default function ToolSelectorContainer({
  toolsData: initialToolsData,
  selectedTools,
  toggleTool,
  removeTool,
  isToolSelected,
  handleDragEnd,
  toggleGroup,
  activeToolTab,
  setActiveToolTab,
  showToolSelector,
  setShowToolSelector,
  toolSearchTerm,
  setToolSearchTerm
}) {
  const [manuallyExpandedItems, setManuallyExpandedItems] = useState<string[]>([]);
  const filteredTools = useMemo(() => {
    const currentTools = initialToolsData[activeToolTab] || [];
    const searchTerm = toolSearchTerm.toLowerCase();

    return currentTools
      .map(tool => {
        const match = tool.name?.toLowerCase().includes(searchTerm) || tool.description?.toLowerCase().includes(searchTerm);
        const matchedChildren = tool.children?.filter(child =>
          child.name?.toLowerCase().includes(searchTerm) || child.desc?.toLowerCase().includes(searchTerm)
        );
        return match || matchedChildren?.length
          ? { ...tool, children: tool.children || [], _forceExpanded: true }
          : null;
      })
      .filter(Boolean);
  }, [initialToolsData, toolSearchTerm, activeToolTab]);

  // Expansion Item Logic 
  const expandedItems = useMemo(() => {
    const searchExpanded = toolSearchTerm
      ? filteredTools.filter(tool => tool._forceExpanded).map(tool => tool.id)
      : [];
    return [...new Set([...searchExpanded, ...manuallyExpandedItems])];
  }, [filteredTools, toolSearchTerm, manuallyExpandedItems]);

  return (
    <ToolSelector
      selectedTools={selectedTools}
      toggleTool={toggleTool}
      removeTool={removeTool}
      isToolSelected={isToolSelected}
      handleDragEnd={handleDragEnd}
      toolsData={initialToolsData}
      activeToolTab={activeToolTab}
      setActiveToolTab={setActiveToolTab}
      toolSearchTerm={toolSearchTerm}
      setToolSearchTerm={setToolSearchTerm}
      filteredTools={filteredTools}
      expandedItems={expandedItems}
      setManuallyExpandedItems={setManuallyExpandedItems}
      toggleGroup={toggleGroup}
      showToolSelector={showToolSelector}
      setShowToolSelector={setShowToolSelector}
    />
  );
}