import { Switch } from "@/components/bs-ui/switch";
import { Button } from "@/components/bs-ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { Input } from "@/components/bs-ui/input";
import { Trash2, Search, Info, RefreshCcw, ChevronDown } from "lucide-react";
import { useState, useEffect, useMemo } from "react";
import { DatePicker } from "@/components/bs-ui/calendar/datePicker";
import { generateUUID } from "@/components/bs-ui/utils";
import { Badge } from "@/components/bs-ui/badge";
import InputItem from "./InputItem";
import { format } from "date-fns";
import { getKnowledgeDetailApi } from "@/controllers/API";
import SelectVar from "./SelectVar";

interface MetadataCondition {
  id: string;
  metadataField: string;
  operator: string;
  valueType: "reference" | "input";
  value: string;
}

interface MetadataField {
  id: string;
  name: string;
  type: "String" | "Number" | "Time";
  knowledgeBase: string;
  updatedAt: number;
  icon: string;
}

interface MetadataFilterProps {
  data: any;
  onChange: (value: any) => void;
  onValidate: (validate: any) => void;
  selectedKnowledgeIds?: () => string[]; // 改为函数类型
}

const MetadataFilter = ({
  data,
  onChange,
  onValidate,
  selectedKnowledgeIds = () => [],
   nodeId
}: MetadataFilterProps) => {
  const [isEnabled, setIsEnabled] = useState(false);
  const [conditions, setConditions] = useState<MetadataCondition[]>(() => {
    if (data.value?.conditions) {
      return data.value.conditions.map(cond => ({
        id: cond.id || generateUUID(8),
        metadataField: cond.metadata_filed || "",
        operator: cond.comparison_operation || "",
        valueType: cond.right_value_type === "ref" ? "reference" : "input",
        value: cond.right_value || "",
      }));
    }
    return [];
  });
  const [relation, setRelation] = useState<"and" | "or">("and");
  const [searchTerm, setSearchTerm] = useState("");
  const [required, setRequired] = useState(false);
  const [availableMetadataState, setAvailableMetadataState] = useState<MetadataField[]>([]);
  const [isLoadingMetadata, setIsLoadingMetadata] = useState(false);
  const [isSelectOpen, setIsSelectOpen] = useState(false);

  const operatorConfig = {
    String: ["equals", "not_equals", "contains", "not_contains", "empty", "not_empty", "starts_with", "ends_with"],
    Number: ["equals", "not_equals", "greater_than", "less_than", "greater_equal", "less_equal"],
    Time: ["equals", "not_equals", "empty", "not_empty", "greater_than", "less_than", "greater_equal", "less_equal"],
  };
  const operatorLabels = {
    equals: "等于",
    not_equals: "不等于",
    contains: "包含",
    not_contains: "不包含",
    empty: "为空",
    not_empty: "不为空",
    starts_with: "开始为",
    ends_with: "结束为",
    regex: "正则",
    greater_than: ">",
    less_than: "<",
    greater_equal: "≥",
    less_equal: "≤",
  };

  // 获取元数据的函数
  const fetchAndPrepareMetadata = async () => {
    setIsLoadingMetadata(true);
    let availableMetadata: MetadataField[] = [];
    try {
      const knowledgeIds = selectedKnowledgeIds();
      console.log("MetadataFilter获取知识库ID:", knowledgeIds);

      if (knowledgeIds.length > 0) {
        const knowledgeDetails = await getKnowledgeDetailApi(knowledgeIds);
        knowledgeDetails.forEach((detail: any) => {
          const kbLabel = detail.name || detail.label || "未知知识库";
          if (detail.metadata_fields && Array.isArray(detail.metadata_fields)) {
            const fields = detail.metadata_fields.map((field: any) => {
              let icon = "📄";
              let type: "String" | "Number" | "Time" = "String";
              if (field.field_type === "number") {
                icon = "#";
                type = "Number";
              } else if (field.field_type === "time") {
                icon = "⏱️";
                type = "Time";
              }
              return {
                id: `${detail.id}-${field.field_name}`,
                name: field.field_name,
                type,
                knowledgeBase: kbLabel,
                updatedAt: field.updated_at || Date.now(),
                icon,
              };
            });
            availableMetadata = [...availableMetadata, ...fields];
          }
        });
      }
    } catch (error) {
      console.error("Error loading metadata:", error);
    } finally {
      availableMetadata.sort((a, b) => b.updatedAt - a.updatedAt);
      setAvailableMetadataState(availableMetadata);
      setIsLoadingMetadata(false);
    }
  };

  // 当打开下拉框或启用状态变化时获取数据
  useEffect(() => {
    if (isEnabled && isSelectOpen) {
      fetchAndPrepareMetadata();
    }
  }, [isSelectOpen, isEnabled])
  // 当启用时获取数据
  useEffect(() => {
    if (isEnabled) {
      fetchAndPrepareMetadata();
    }
  }, [isEnabled]);

  // 监听数据变化，强制刷新
  useEffect(() => {
    // 当组件启用时，立即获取一次数据
    if (isEnabled) {
      fetchAndPrepareMetadata();
    }
  }, [isEnabled]);

  useEffect(() => {
    if (isEnabled) {
      validateConditions();
      const filterData = {
        enabled: true,
        operator: relation,
        conditions: conditions.map(cond => {
          const [knowledgeId] = cond.metadataField.split("-");
          const metaField = availableMetadataState.find(m => m.id === cond.metadataField);
          return {
            id: cond.id,
            knowledge_id: knowledgeId ? parseInt(knowledgeId, 10) : 0,
            metadata_filed: metaField?.name || "",
            comparison_operation: cond.operator,
            right_value_type: cond.valueType === "reference" ? "ref" : "input",
            right_value: cond.value,
          };
        }),
      };
      onChange(filterData);
    } else {
      onChange({ enabled: false });
    }
  }, [conditions, relation, isEnabled, availableMetadataState, onChange]);

  const filteredMetadata = useMemo(() => {
    const term = searchTerm.toLowerCase().trim();
    if (!term) return availableMetadataState;
    return availableMetadataState.filter(meta =>
      meta.name.toLowerCase().includes(term) ||
      meta.knowledgeBase.toLowerCase().includes(term)
    );
  }, [availableMetadataState, searchTerm]);

  const addCondition = () => {
    setRequired(false);
    setConditions(prev => [...prev, {
      id: generateUUID(8),
      metadataField: "",
      operator: "",
      valueType: "input",
      value: "",
    }]);
  };

  const deleteCondition = (id: string) => {
    setConditions(prev => prev.filter(c => c.id !== id));
  };

  const updateCondition = (id: string, field: keyof MetadataCondition, value: string) => {
    setConditions(prev => prev.map(condition => {
      if (condition.id === id) {
        const updated = { ...condition, [field]: value };
        if (field === "operator" && ["empty", "not_empty"].includes(value)) {
          updated.value = "";
        }
        if (field === "metadataField") {
          updated.operator = "";
          updated.value = "";
        }
        return updated;
      }
      return condition;
    }));
  };

  const handleRelationChange = () => {
    setRelation(prev => prev === "and" ? "or" : "and");
  };

  const getConditionMetadataType = (conditionId: string): "String" | "Number" | "Time" | null => {
    const condition = conditions.find(c => c.id === conditionId);
    if (!condition?.metadataField) return null;
    const metadata = availableMetadataState.find(m => m.id === condition.metadataField);
    return metadata?.type || null;
  };

  const validateConditions = () => {
    const isValid = conditions.every(cond => cond.metadataField && cond.operator);
    onValidate({ valid: isValid });
    setRequired(!isValid);
    return isValid;
  };

  const renderValueInput = (condition: MetadataCondition) => {
    const metadataType = getConditionMetadataType(condition.id);
    const isEmptyOperator = ["empty", "not_empty"].includes(condition.operator);

    if (isEmptyOperator) {
      return <Input placeholder="无需输入" value="" disabled className="bg-gray-100 h-8" />;
    }
      if (condition.valueType === "reference") {
      // 查找当前选中值对应的标签
      const selectedLabel = condition.value
        ? condition.value.split('.').reduce((acc, part, index, array) => {
            return index === array.length - 1 ? `${acc}/${part}` : `${acc}.${part}`;
          })
        : "";

      return (
        <div className="flex items-center gap-1 min-w-0">
          <SelectVar
              className="max-w-40 flex-1" // 使用 flex-1 让其占据可用空间
              nodeId={nodeId} // 假设 nodeId 在当前组件作用域内可用
              itemKey={condition.id}
              onSelect={(E, v) => {
                  const selectedValue = `${E.id}.${v.value}`;
                  updateCondition(condition.id, "value", selectedValue);
              }}
          >
              <div
                  className={`no-drag nowheel group flex h-8 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-search-input px-3 py-1 text-sm shadow-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1 data-[placeholder]:text-gray-400`}
              >
                  <span className="flex items-center flex-1 truncate">{selectedLabel || "选择变量"}</span>
                  <ChevronDown className="h-5 w-5 min-w-5 opacity-80 group-data-[state=open]:rotate-180" />
              </div>
          </SelectVar>
          {metadataType === "Time" && (
            <div className="relative group/info flex-shrink-0 ml-1">
              <Info size={16} className="text-gray-400 cursor-help" />
              <div className="absolute bottom-full left-0 mb-2 hidden group-hover/info:block w-64 p-2 bg-black text-white text-xs rounded z-10">
                引用变量格式为 "YYYY-MM-DDTHH:mm:ss"
              </div>
            </div>
          )}
        </div>
      );
    }
    if (metadataType === "String") {
      return <Input placeholder={condition.operator === "regex" ? "输入正则表达式" : "请输入文本"} value={condition.value} onChange={(e) => updateCondition(condition.id, "value", e.target.value)} maxLength={255} className="h-8" />;
    }
    if (metadataType === "Number") {
      return <InputItem type="number" data={{ value: condition.value, label: "" }} onChange={(e) => updateCondition(condition.id, "value", e.target.value)} />;
    }
    if (metadataType === "Time") {
      return <DatePicker value={condition.value ? new Date(condition.value) : undefined} showTime onChange={(d) => updateCondition(condition.id, "value", d ? format(d, "yyyy-MM-dd'T'HH:mm:ss") : "")} />;
    }
    return <Input placeholder="输入值" value={condition.value} onChange={(e) => updateCondition(condition.id, "value", e.target.value)} className="h-8" />;
  };

  return (
    <div className="space-y-4 rounded-lg min-w-0 mb-4">
      <div className="flex items-center justify-between min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-500">元数据过滤</span>
        </div>
        <Switch checked={isEnabled} onCheckedChange={setIsEnabled} />
      </div>

      {isEnabled && (
        <div className="space-y-3 min-w-0">
          <div className="space-y-2 min-w-0 relative">
            {conditions.length > 1 && (
              <div className="absolute left-1 top-0 w-4 h-full py-4">
                <div className="h-full border border-foreground border-dashed border-r-0 rounded-l-sm">
                  <Badge variant="outline" className="absolute top-1/2 left-0.5 -translate-x-1/2 -translate-y-1/2 px-1 py-0 text-primary bg-[#E6ECF6] cursor-pointer" onClick={handleRelationChange}>
                    {relation} <RefreshCcw size={12} />
                  </Badge>
                </div>
              </div>
            )}
            {conditions.map((condition) => {
              const metadataType = getConditionMetadataType(condition.id);
              const isTimeType = metadataType === "Time";

              return (
                <div key={condition.id} className="relative group pl-10">
                  <div className="flex gap-2 items-center min-w-0">
                    <div className={`flex-1 min-w-0 ${isTimeType ? 'max-w-[15%]' : 'max-w-[25%]'}`}>
                      <Select
                        value={condition.metadataField}
                        onValueChange={(value) => updateCondition(condition.id, "metadataField", value)}
                        onOpenChange={setIsSelectOpen}
                      >
                        <SelectTrigger
                          className={`h-8 min-w-0 ${required && !condition.metadataField && 'border-red-500'}`}
                        >
                          <SelectValue placeholder="选择变量">
                            {condition.metadataField && (
                              <>
                                {
                                  (() => {
                                    const meta = availableMetadataState.find(m => m.id === condition.metadataField);
                                    return meta ? `${meta.icon} ${meta.name}` : '选择变量';
                                  })()
                                }
                              </>
                            )}
                          </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                          <div className="max-h-60 overflow-y-auto">
                            {isLoadingMetadata && (
                              <div className="p-4 text-center text-sm text-gray-500">
                                正在加载元数据字段...
                              </div>
                            )}

                            {!isLoadingMetadata && (
                              <>
                                <div className="p-2 border-b">
                                  <div className="relative">
                                    <Search className="absolute left-3 top-2.5 h-3 w-3 text-muted-foreground" />
                                    <input
                                      type="text"
                                      placeholder="搜索元数据"
                                      className="w-full pl-8 pr-2 py-1 text-[8px] border rounded"
                                      value={searchTerm}
                                      onChange={(e) => setSearchTerm(e.target.value)}
                                      onClick={(e) => e.stopPropagation()}
                                    />
                                  </div>
                                </div>

                               {filteredMetadata.length > 0 ? (
  filteredMetadata.map((meta) => (
    <SelectItem
      key={meta.id}
      value={meta.id}
      showIcon={false}
      className="pr-4"
    >
      <div className="grid grid-cols-[auto_auto_1fr_auto] items-center w-full gap-1">
        <span className="flex-shrink-0">{meta.icon}</span>
        <span className="text-xs text-muted-foreground flex-shrink-0">{meta.type}</span>
        <span className="truncate">{meta.name}</span>
        <span className="text-xs text-gray-500 ml-2 flex-shrink-0 truncate max-w-[80px]">
          {meta.knowledgeBase}
        </span>
      </div>
    </SelectItem>
  ))
) : (
                                  <div className="p-4 text-center text-sm text-gray-500">
                                    暂无元数据字段
                                  </div>
                                )}
                              </>
                            )}
                          </div>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className={`flex-1 min-w-0 ${isTimeType ? 'max-w-[15%]' : 'max-w-[20%]'}`}>
                      <Select
                        value={condition.operator}
                        onValueChange={(value) => updateCondition(condition.id, "operator", value)}
                        disabled={!condition.metadataField}
                      >
                        <SelectTrigger className={`h-8 min-w-0 ${required && !condition.operator && 'border-red-500'}`}>
                          <SelectValue placeholder="选择条件" />
                        </SelectTrigger>
                        <SelectContent>
                          {metadataType && operatorConfig[metadataType].map((op) => (
                            <SelectItem key={op} value={op}>{operatorLabels[op]}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className={`flex-1 min-w-0 ${isTimeType ? 'max-w-[15%]' : 'max-w-[20%]'}`}>
                      <Select
                        value={condition.valueType}
                        onValueChange={(value: "reference" | "input") => updateCondition(condition.id, "valueType", value)}
                        disabled={!condition.metadataField || ["empty", "not_empty"].includes(condition.operator)}
                      >
                        <SelectTrigger className="h-8 min-w-0"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="reference">引用</SelectItem>
                          <SelectItem value="input">输入</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className={`flex-1 min-w-0 ${isTimeType ? 'max-w-[45%]' : 'max-w-[25%]'}`}>
                      {renderValueInput(condition)}
                    </div>
                    <div className={`flex-shrink-0 ${isTimeType ? 'max-w-[10%]' : 'max-w-[10%]'} flex justify-center`}>
                      <Trash2
                        size={14}
                        onClick={() => deleteCondition(condition.id)}
                        className="hover:text-red-600 cursor-pointer group-hover:opacity-100 opacity-0"
                      />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          <Button
            onClick={addCondition}
            variant="outline"
            className="border-primary text-primary mt-2 h-8"
          >
            + 添加条件
          </Button>
        </div>
      )}
    </div>
  );
};

export default MetadataFilter;