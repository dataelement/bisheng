import { isNumberDraftWithinBounds } from '@/utils/fieldValidation';
import { Button, Input } from '@bisheng/ui';
import { TimeRangeType } from "../../types/dataConfig";

import { Dialog,DialogContent,DialogFooter,DialogHeader,DialogTitle } from "@/components/bs-ui/dialog";

import { Label } from "@/components/bs-ui/label";
import { generateUUID } from "@/components/bs-ui/utils";
import { RadioGroup,Radio as RadioGroupItem } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";

import { ChartType,QueryConfig,TimeRangeMode } from "../../types/dataConfig";
import { AdvancedDatePicker } from "../AdvancedDatePicker";
import ComponentPicker,{ ChartGroupItems } from "../editor/ComponentPicker";
import ChartSelector from "./ChartSelector";
import type { useComponentConfigController } from "./ComponentConfigDrawer";
import { DashboardConfigPanel } from "./DashboardConfigPanel";
import { FULL_DEFAULT_STYLE_CONFIG } from "./dashboardStyleDefaults";
import { DatasetSelector } from "./DatasetSelector";
import { DimensionBlock } from "./DimensionBlock";
import { FilterConditionDialog } from "./FilterConditionDialog";
import { StyleConfigPanel } from "./StyleConfigPanel";
interface ComponentConfigViewProps { controller: ReturnType<typeof useComponentConfigController> }
export function ComponentConfigView({ controller }: ComponentConfigViewProps) {
const {
  handleCloseQuery, editingComponent, configCollapsed, toggleCollapse, updateEditingComponent, refreshChart,
  CollapseLabel, t, PanelHeader, Tab, configTab, setConfigTab,
  FormBlock, handleChartTypeChange, chartType, title, valueDimensions, setTitle,
  limitType, limitValue, getDataConfig, currentChartHasStack, chartState, styleConfig,
  isMetricCard, CollapsibleBlock, invalidFieldIds, categoryDimensions, dragOverSection, handleDragOver,
  handleDragLeave, handleDrop, handleDeleteDimension, handleSortChange, openEditDialog, isStackedChart,
  stackDimensions, handleAggregationChange, handleMetricFormatChange, sortPriorityFields, setDraggingId, handleDropSortPriority,
  draggingId, filterGroup, handleEditFilter, handleDeleteFilter, filter, handleTimeFilterChange,
  setFilter, setLimitType, setLimitValue, handleUpdateChart, handleDatasetChange, handleDragStart,
  setDatasetFields, handleFieldClick, editDialogOpen, setEditDialogOpen, editingDimension, setEditingDimension,
  saveDisplayName, filterDialogOpen, setFilterDialogOpen, handleSaveFilter, datasetFields } = controller;
if (!editingComponent) {
    return (
      <DashboardConfigPanel
        collapsed={configCollapsed.basic}
        onCollapse={() => toggleCollapse('basic')}
      />
    )
  }
return (
    <div className="h-full flex bg-background border-l border-border">
      {editingComponent.type === 'query' ? (
        <ChartSelector
          onSave={(chartLinkConfig) => {
            const { dateRange } = chartLinkConfig

            const queryConfig: QueryConfig = {
              linkedComponentIds: chartLinkConfig.chartIds || [],
              queryConditions: {
                id: ('queryConditions' in editingComponent.data_config ? editingComponent.data_config.queryConditions.id : undefined) || generateUUID(4),
// These labels are part of the existing query configuration protocol.
// eslint-disable-next-line no-restricted-syntax
                displayType: chartLinkConfig.displayType === "时间" ? "single" : "range",
// These labels are part of the existing query configuration protocol.
// eslint-disable-next-line no-restricted-syntax
                timeGranularity: chartLinkConfig.timeGranularity === "年月" ? "year_month" :
// These labels are part of the existing query configuration protocol.
// eslint-disable-next-line no-restricted-syntax
                  chartLinkConfig.timeGranularity === "年月日时" ? "year_month_day_hour" : "year_month_day",
                hasDefaultValue: chartLinkConfig.isDefault,
                defaultValue: chartLinkConfig.isDefault ? {
                  shortcutKey: chartLinkConfig.dateRange.shortcutKey ? parseInt(chartLinkConfig.dateRange.shortcutKey.replace('last_', '')) : undefined,
                  // startDate: new Date(chartLinkConfig.dateRange.start).getTime(),
                  // endDate: new Date(chartLinkConfig.dateRange.end).getTime(),
                  type: chartLinkConfig.dateRange.shortcutKey ? TimeRangeType.RECENT_DAYS : TimeRangeType.CUSTOM,
                  mode: dateRange.isDynamic ? TimeRangeMode.Dynamic : TimeRangeMode.Fixed,
                  recentDays: dateRange.shortcutKey ? parseInt(dateRange.shortcutKey.replace('last_', '')) : undefined,
                  startDate: dateRange.start,
                  endDate: dateRange.end
                } : {
                  type: TimeRangeType.ALL
                }
              }
            }

            updateEditingComponent({

              data_config: queryConfig
            })
            // const dashboardStore = useEditorDashboardStore.getState();
            // dashboardStore.updateComponent(editingComponent.id, {
            //   data_config: queryConfig
            // })

            refreshChart(editingComponent.id)
          }}
          onCancel={() => {
            handleCloseQuery()
          }}
        />
      ) : (
        <>
          <div className={`border-r flex flex-col h-full transition-all duration-300 ${configCollapsed.basic ? "w-12" : "w-[260px]"} shrink-0`}>
            {configCollapsed.basic ? (
              <CollapseLabel
                label={t("componentConfigDrawer.basicConfig")}
                styleLabel={t("componentConfigDrawer.styleConfigTab")}
                onClick={() => toggleCollapse('basic')}
                icon={<Outlined.Left className="w-4 h-4" />}
              />
            ) : (
              <div className="flex-1 flex flex-col overflow-hidden">
                <PanelHeader
                  title={t("componentConfigDrawer.basicConfig")}
                  onCollapse={() => toggleCollapse('basic')}
                  icon={<Outlined.Right className="w-4 h-4" />}
                />
                <div className="flex-1 overflow-y-auto pl-4 pr-4 pb-6 pt-4 space-y-6">
                  <div className="border-b -mx-4 px-4">
                    <div className="flex gap-6 text-sm">
                      <Tab active={configTab === "basic"} onClick={() => setConfigTab("basic")}>
                        {t("componentConfigDrawer.basicConfigTab")}
                      </Tab>
                      <Tab active={configTab === "style"} onClick={() => setConfigTab("style")}>
                        {t("componentConfigDrawer.styleConfigTab")}
                      </Tab>
                    </div>
                  </div>
                  {configTab === "basic" ? (
                    <>
                      {
                        editingComponent.type !== 'metric' && (
                          <>
                            {/* chart type */}
                            <FormBlock label={t("componentConfigDrawer.chartType")} required>
                              <ComponentPicker onSelect={(data) => {

                                handleChartTypeChange(data.type);

                                const isMetricChart = data.type === 'metric';
                                const chartLabel = ChartGroupItems
                                  .flatMap(item => item.data)
                                  .find(item => item.type === data.type)?.label;

                                const currentChartLabel = ChartGroupItems
                                  .flatMap(item => item.data)
                                  .find(item => item.type === chartType)?.label;
                                const currentChartDisplayName = currentChartLabel ? t(`chart.${currentChartLabel}`) : '';
                                let newTitle = title;
                                if (isMetricChart) {
                                  if (valueDimensions.length > 0) {
                                    newTitle = valueDimensions[0].displayName;
                                  }
                                } else {
                                  const userCustomizedTitle = editingComponent.title !== currentChartDisplayName && editingComponent.title !== '';
                                  newTitle = userCustomizedTitle ? editingComponent.title : (chartLabel ? t(`chart.${chartLabel}`) : title);
                                }
                                if (!isMetricChart && chartLabel) {
                                  setTitle(newTitle);
                                }

                                if (editingComponent) {

                                  const currentLimitType = limitType;
                                  const currentLimitValue = limitValue;

                                  const dataConfig = getDataConfig(currentLimitType, currentLimitValue, ('timeFilter' in editingComponent.data_config ? editingComponent.data_config.timeFilter : undefined));

                                  const STACKED_CHART_TYPES = new Set<ChartType>([
                                    ChartType.StackedBar,
                                    ChartType.StackedHorizontalBar,
                                    ChartType.StackedLine
                                  ]);
                                  const isNewChartStacked = STACKED_CHART_TYPES.has(data.type);
                                  const isCurrentChartStacked = currentChartHasStack;
                                  let updatedDataConfig = { ...dataConfig };
                                  if (isMetricChart) {
                                    updatedDataConfig = {
                                      ...updatedDataConfig,
                                      stackDimension: undefined,
                                      dimensions: updatedDataConfig.dimensions || [],
                                      metrics: updatedDataConfig.metrics[0] ? [updatedDataConfig.metrics[0]] : []
                                    }
                                  }

                                  if (isCurrentChartStacked && !isNewChartStacked) {

                                    updatedDataConfig = {
                                      ...updatedDataConfig,
                                      stackDimension: undefined,
                                      dimensions: updatedDataConfig.dimensions || [],
                                      metrics: updatedDataConfig.metrics || []
                                    };
                                  } else if (!isCurrentChartStacked && isNewChartStacked) {

                                    updatedDataConfig = {
                                      ...updatedDataConfig,
                                      stackDimension: undefined,
                                      dimensions: updatedDataConfig.dimensions || [],
                                      metrics: updatedDataConfig.metrics || []
                                    };
                                  }
                                  if (data.type === 'metric') {
                                    const firstMetric = valueDimensions[0] ? { ...valueDimensions[0] } : null;

                                    chartState.setValueDimensions(firstMetric ? [firstMetric] : []);
                                    chartState.setCategoryDimensions([]);
                                    chartState.setStackDimensions([]);
                                    updateEditingComponent({
                                      type: data.type,
                                      data_config: updatedDataConfig,
                                      title: newTitle,
                                      style_config: {
                                        ...styleConfig
                                      },
                                      dataset_code: editingComponent.dataset_code
                                    });
                                  } else {
                                    updateEditingComponent({
                                      type: data.type,
                                      data_config: updatedDataConfig,
                                      title: newTitle,
                                      style_config: {
                                        ...styleConfig,
                                        title: newTitle
                                      },
                                      dataset_code: editingComponent.dataset_code
                                    });
                                  }

                                  refreshChart(editingComponent.id);
                                }
                              }} maxHeight={400}>
                                <div className="relative w-full group">
                                  <div className="flex h-[28px] w-full items-center justify-between rounded-md border hover:border-muted-foreground/40 px-3 py-2 text-sm transition-colors cursor-pointer">

                                    <div className="flex items-center gap-2 flex-1 min-w-0">
                                      <img
                                        src={`${__APP_ENV__.BASE_URL}/assets/dashboard/${chartType}.png`}
                                        className="w-4 h-4 shrink-0"
                                        alt={chartType}
                                      />
                                      <span className="truncate text-foreground">
                                        {t(
                                          `chart.${ChartGroupItems
                                            .flatMap(item => item.data)
                                            .find(item => item.type === chartType)?.label}`
                                        ) || t("componentConfigDrawer.selectChartType")}
                                      </span>
                                    </div>
                                    {/* ChevronDown */}
                                    <Outlined.Down className="h-4 w-4 text-gray-500 flex-shrink-0" />
                                  </div>
                                </div>
                              </ComponentPicker>
                            </FormBlock>

                            {isMetricCard && (
                              <>
                                <CollapsibleBlock
                                  title={t("componentConfigDrawer.categoryAxis")}
                                  required
                                  collapsed={configCollapsed.category}
                                  onCollapse={() => toggleCollapse('category')}
                                >
                                  <DimensionBlock
                                    invalidIds={invalidFieldIds}
                                    isDimension={true}
                                    dimensions={categoryDimensions}
                                    maxDimensions={2}
                                    isDragOver={dragOverSection === 'category'}
                                    onDragOver={(e) => handleDragOver(e, 'category')}
                                    onDragLeave={handleDragLeave}
                                    onDrop={(e) => handleDrop(e, 'category', isMetricCard)}
                                    onDelete={(dimensionId) => handleDeleteDimension('category', dimensionId)}
                                    onSortChange={(dimensionId, sortValue) => handleSortChange('category', dimensionId, sortValue)}
                                    onEditDisplayName={(dimensionId, originalName, displayName) =>
                                      openEditDialog('category', dimensionId, originalName, displayName)
                                    }
                                  />
                                </CollapsibleBlock>
                                {currentChartHasStack && (
                                  <CollapsibleBlock
                                    title={isStackedChart(chartType) ? t("componentConfigDrawer.subCategory") : t("componentConfigDrawer.stackItem")}
                                    collapsed={configCollapsed.stack}
                                    onCollapse={() => toggleCollapse('stack')}
                                  >
                                    <DimensionBlock
                                      invalidIds={invalidFieldIds}
                                      isDimension={true}
                                      isStack={'stack'}
                                      dimensions={stackDimensions}
                                      isDragOver={dragOverSection === 'stack'}
                                      onDragOver={(e) => handleDragOver(e, 'stack')}
                                      onDragLeave={handleDragLeave}
                                      onDrop={(e) => handleDrop(e, 'stack', isMetricCard)}
                                      onDelete={(dimensionId) => handleDeleteDimension('stack', dimensionId)}
                                      onSortChange={(dimensionId, sortValue) => handleSortChange('stack', dimensionId, sortValue)}
                                      onEditDisplayName={(dimensionId, originalName, displayName) =>
                                        openEditDialog('stack', dimensionId, originalName, displayName)
                                      }
                                    />
                                  </CollapsibleBlock>
                                )}
                              </>
                            )}
                          </>
                        )
                      }

                      <CollapsibleBlock
                        title={t("componentConfigDrawer.valueAxis")}
                        required
                        collapsed={configCollapsed.value}
                        onCollapse={() => toggleCollapse('value')}
                      >
                        <DimensionBlock
                          onAggregationChange={handleAggregationChange}
                          isMetricCard={isMetricCard}
                          invalidIds={invalidFieldIds}
                          isDimension={false}
                          dimensions={valueDimensions}
                          isDragOver={dragOverSection === 'value'}
                          onDragOver={(e) => handleDragOver(e, 'value')}
                          onDragLeave={handleDragLeave}
                          onDrop={(e) => handleDrop(e, 'value', isMetricCard)}
                          onDelete={(dimensionId) => handleDeleteDimension('value', dimensionId)}
                          onSortChange={(dimensionId, sortValue) => handleSortChange('value', dimensionId, sortValue)}
                          onEditDisplayName={(dimensionId, originalName, displayName) =>
                            openEditDialog('value', dimensionId, originalName, displayName)
                          }
                          onFormatChange={handleMetricFormatChange}
                        />
                      </CollapsibleBlock>

                      {(editingComponent.type !== 'metric' && isMetricCard) && <CollapsibleBlock title={t("componentConfigDrawer.sortPriority")}>
                        <div className="space-y-1 border rounded-md p-[2px]">
                          {sortPriorityFields?.length === 0 ? (
                            <div className="text-xs text-muted-foreground text-center py-2">
                              {t("componentConfigDrawer.sortHint")}
                            </div>
                          ) : (
                            sortPriorityFields.map((field) => (
                              <div
                                key={field.id}
                                draggable
                                onMouseDown={() => { }}
                                onDragStart={(e) => {
                                  setDraggingId(field.id)
                                  e.dataTransfer.effectAllowed = 'move'
                                  e.dataTransfer.setData('text/plain', field.id)
                                }}
                                onDragEnd={() => setDraggingId(null)}
                                onDragOver={(e) => e.preventDefault()}
                                onDrop={(e) => {
                                  e.preventDefault()
                                  const sourceId = e.dataTransfer.getData('text/plain')
                                  if (!sourceId) return
                                  handleDropSortPriority(field)
                                }}
                                className={`flex items-center gap-2 px-3 py-2 h-[28px] border rounded-md bg-muted/20 ${draggingId === field.id ? 'opacity-50' : ''}`}
                              >
                                <Outlined.Drag className="h-4 w-4 text-muted-foreground cursor-grab" />
                                <span className="text-sm truncate">{field.displayName}</span>
                              </div>
                            ))
                          )}
                        </div>
                      </CollapsibleBlock>}

                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <label className="text-sm font-medium">{t("componentConfigDrawer.filter")}</label>
                        </div>
                        {!filterGroup || filterGroup.conditions.length === 0 ? (
                          <div
                            className="text-sm text-muted-foreground text-center w-[216px] h-[36px] py-2 border rounded-md bg-muted/20 cursor-pointer hover:bg-muted/30 transition-colors"
                            onClick={handleEditFilter}
                          >
                            <div className="inline-flex items-center h-[20px] px-2 text-xs">
                              {t("componentConfigDrawer.addFilterCondition")}
                            </div>
                          </div>
                        ) : (
                          <div className="space-y-2 bg-blue-100 rounded-md border-blue-300 group">
                            <div className="flex items-center justify-between p-2 border rounded-md bg-muted/20 hover:bg-muted/40">
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-medium text-blue-700">
                                  {t("componentConfigDrawer.filterConditionsAdded", { count: filterGroup.conditions.length })}
                                </span>
                              </div>
                              <div className="opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex items-center gap-1">
                                <Button variant="text" size="medium" className="h-6 w-6" onClick={handleEditFilter} color="default" iconOnly>
                                  <Outlined.Edit className="h-3 w-3" />
                                </Button>
                                <Button variant="text" size="medium" className="h-6 w-6" onClick={handleDeleteFilter} color="default" iconOnly>
                                  <Outlined.Close className="h-3 w-3" />
                                </Button>
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
                      <FormBlock label={t("componentConfigDrawer.timeRange")}>
                        <div className="space-y-1 flex flex-1 w-full">
                          <AdvancedDatePicker
                            granularity={'day'}
                            mode={'range'}
                            value={filter}
                            onChange={(val) => {
                              handleTimeFilterChange(val);
                              setFilter(val);
                            }}
                            placeholder={t("componentConfigDrawer.selectTimeRange")}
                          />
                        </div>
                      </FormBlock>
                      {/* <Button id="config_save" className="w-full h-10 mt-4" onClick={handleUpdateChart}>
                        {t("componentConfigDrawer.updateChartData")}
                      </Button> */}
                    </>
                  ) : (
                    <StyleConfigPanel
                      config={editingComponent?.style_config || styleConfig}
                      type={editingComponent.type}
                      FULL_DEFAULT_STYLE_CONFIG={FULL_DEFAULT_STYLE_CONFIG}
                      onChange={(newConfig) => {
                        chartState.setStyleConfig(newConfig)
                        if (editingComponent) {
                          updateEditingComponent({
                            title: newConfig.title,
                            style_config: newConfig
                          })
                        }
                      }}
                      key={editingComponent.id}
                    />
                  )}
                </div>

                {configTab !== "style" && <div className="px-4 py-3 border-t bg-background">

                  {(editingComponent.type !== 'metric' && isMetricCard) &&
                    <div>
                      <RadioGroup
                        value={limitType}
                        onValueChange={(value: "all" | "limit") => setLimitType(value)}
                        className="flex justify-between gap-4"
                      >
                        <div className=" text-sm font-medium mt-1">
                          {t("componentConfigDrawer.resultsDisplay")}
                        </div>
                        <div className="flex">
                          <div className="flex items-center space-x-2 mr-1">
                            <RadioGroupItem value="all" id="limit-all" />
                            <Label htmlFor="limit-all" className="text-sm cursor-pointer whitespace-nowrap">
                              {t("componentConfigDrawer.allResults")}
                            </Label>
                          </div>
                          <div className="flex items-center space-x-2">
                            <RadioGroupItem value="limit" id="limit-limit" />
                            <div className="flex items-center gap-2">
                              <Input type="number" value={limitValue} disabled={limitType !== "limit"} onChange={(e) => { if (!isNumberDraftWithinBounds(e.currentTarget.value, { min: 1, max: 1000 })) return; const value = e.target.value;
if (value === '' || /^\d+$/.test(value)) {
                                    const num = parseInt(value);
                                    if (value === '' || (num >= 1 && num <= 1000)) {
                                      setLimitValue(value);
                                    }
                                  } }} onBlur={(e) => {
                                  const value = e.target.value;
                                  const num = parseInt(value);
                                  if (value === '' || isNaN(num)) {
                                    setLimitValue('1');
                                  } else if (num < 1) {
                                    setLimitValue('1');
                                  } else if (num > 1000) {
                                    setLimitValue('1000');
                                  } else {
                                    setLimitValue(num.toString());
                                  }
                                }} min={1} max={1000} placeholder="1000" className={"w-16 h-7 text-sm appearance-none [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"} />
                            </div>
                          </div>
                        </div>
                      </RadioGroup>
                    </div>
                  }
                  <Button id="config_save" className="w-full h-10 mt-[12px]" onClick={handleUpdateChart}>
                    {t("componentConfigDrawer.updateChartData")}
                  </Button>
                </div>}
              </div>
            )}
          </div>
          <div className={`flex flex-col h-full transition-all duration-300 ${configCollapsed.data ? "w-12 shrink-0" : "w-[180px]"}`}>
            {configCollapsed.data ? (
              <CollapseLabel
                label={t("componentConfigDrawer.dataSelection")}
                onClick={() => toggleCollapse('data')}
                icon={<Outlined.Left className="w-4 h-4" />}
              />
            ) : (
              <div className="flex-1 flex flex-col overflow-hidden">
                <PanelHeader
                  title={t("componentConfigDrawer.dataSelection")}
                  onCollapse={() => toggleCollapse('data')}
                  icon={<Outlined.Right className="w-4 h-4" />}
                />
                <div className="flex-1 overflow-auto">
                  <DatasetSelector
                    isMetricCard={editingComponent?.type === 'metric'}
                    selectedDatasetCode={editingComponent.dataset_code}
                    onDatasetChange={handleDatasetChange}
                    onDragStart={handleDragStart}
                    onFieldsLoaded={setDatasetFields}
                    onFieldClick={handleFieldClick}
                  />
                </div>
              </div>
            )}
          </div>
        </>
      )}

      <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
        <DialogContent className="sm:max-w-[400px]">
          <DialogHeader>
            <DialogTitle>{t("componentConfigDrawer.dialog.editDisplayName")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div>
              <div className="text-sm text-muted-foreground mb-1">
                {t("componentConfigDrawer.dialog.originalName")}
              </div>
              <div className="text-sm font-medium px-2 py-1 bg-muted rounded">{editingDimension?.originalName}</div>
            </div>
            <div>
              <div className="text-sm font-medium mb-1">
                {t("componentConfigDrawer.dialog.displayNameRequired")}
              </div>
              <Input value={editingDimension?.displayName || ''} onChange={(e) => setEditingDimension(prev => prev ? { ...prev, displayName: e.target.value } : null)} placeholder={t("componentConfigDrawer.dialog.enterDisplayName")} maxLength={15} className={(editingDimension?.displayName?.length || 0) >= 15 ? 'border-red-500 focus-visible:ring-red-500' : ''} showCount />
              {(editingDimension?.displayName?.length || 0) >= 15 && (
                <div className="text-xs text-red-500 mt-1">
                  {t("componentConfigDrawer.dialog.displayMaxLength", { max: 15 })}
                </div>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outlined" onClick={() => setEditDialogOpen(false)} color="default">
              {t("componentConfigDrawer.dialog.cancel")}
            </Button>
            <Button onClick={saveDisplayName}>
              {t("componentConfigDrawer.dialog.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <FilterConditionDialog
        open={filterDialogOpen}
        onOpenChange={setFilterDialogOpen}
        value={filterGroup}
        onChange={handleSaveFilter}
        fields={datasetFields}
        dataset_code={editingComponent?.dataset_code}
        filtersLogic={('filtersLogic' in editingComponent.data_config ? editingComponent.data_config.filtersLogic : undefined)}
        dimensions={[...categoryDimensions, ...stackDimensions, ...valueDimensions]}
      />
    </div>
  )
}
