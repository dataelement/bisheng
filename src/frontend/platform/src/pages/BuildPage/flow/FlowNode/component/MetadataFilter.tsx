import { Switch } from "@/components/bs-ui/switch";
import { Button } from "@/components/bs-ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { Input } from "@/components/bs-ui/input";
import { Trash2, Search, Info, RefreshCcw, ChevronDown, Clock3, Type, Hash, CircleQuestionMark, AlertCircle } from "lucide-react";
import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { DatePicker } from "@/components/bs-ui/calendar/datePicker";
import { generateUUID } from "@/components/bs-ui/utils";
import { Badge } from "@/components/bs-ui/badge";
import { format } from "date-fns";
import { getKnowledgeDetailApi } from "@/controllers/API";
import SelectVar from "./SelectVar";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import NumberInput from "./NumberInput";
import { isVarInFlow } from "@/util/flowUtils";
import useFlowStore from "../../flowStore";

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
  icon: React.ReactNode;
  isDefault: boolean;
}

interface MetadataFilterProps {
  data: any;
  onChange: (value: any) => void;
  onValidate: (validate: any) => void;
  selectedKnowledgeIds?: () => string[];
  nodeId?: string;
  node?: any;
}

const MetadataFilter = ({
  data,
  onChange,
  onValidate,
  selectedKnowledgeIds = () => [],
  nodeId,
  node
}: MetadataFilterProps) => {

  const isInitialMount = useRef(true);
  const isUpdatingFromExternal = useRef(false);
  const validateTimer = useRef<NodeJS.Timeout | null>(null);
  const { flow } = useFlowStore();

  const [isEnabled, setIsEnabled] = useState(data.value?.enabled ?? false);
  const [conditions, setConditions] = useState<MetadataCondition[]>(() => {
    if (data.value?.conditions && Array.isArray(data.value.conditions)) {
      return data.value.conditions.map(cond => ({
        id: cond.id || generateUUID(8),
        metadataField: cond.knowledge_id && cond.metadata_field
          ? `${cond.knowledge_id}-${cond.metadata_field}`
          : "",
        operator: cond.comparison_operation || "",
        valueType: cond.right_value_type === "ref" ? "reference" : "input",
        value: cond.right_value || "",
      }));
    }
    return [];
  });
  const [relation, setRelation] = useState<"and" | "or">(() => {
    return data.value?.operator === "or" ? "or" : "and";
  });
  const [searchTerm, setSearchTerm] = useState("");
  const [required, setRequired] = useState(false);
  const [availableMetadataState, setAvailableMetadataState] = useState<MetadataField[]>([]);
  const [isLoadingMetadata, setIsLoadingMetadata] = useState(false);
  const [isSelectOpen, setIsSelectOpen] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<{ [key: string]: string }>({});

  // 节点变化检测状态
  const [knowledgeIdsStr, setKnowledgeIdsStr] = useState("");

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

          const defaultFields = [
            { name: "document_id", type: "Number", icon: <Hash size={14} /> },
            { name: "document_name", type: "String", icon: <Type size={14} /> },
            { name: "upload_time", type: "Time", icon: <Clock3 size={14} /> },
            { name: "update_time", type: "Time", icon: <Clock3 size={14} /> },
            { name: "uploader", type: "String", icon: <Type size={14} /> },
            { name: "updater", type: "String", icon: <Type size={14} /> }
          ];

          const defaultMetadataFields = defaultFields.map(field => ({
            id: `${detail.id}-${field.name}`,
            name: field.name,
            type: field.type as "String" | "Number" | "Time",
            knowledgeBase: kbLabel,
            updatedAt: Date.now(),
            icon: field.icon,
            isDefault: true
          }));

          availableMetadata = [...availableMetadata, ...defaultMetadataFields];

          if (detail.metadata_fields && Array.isArray(detail.metadata_fields)) {
            const customFields = detail.metadata_fields.map((field: any) => {
              let icon: React.ReactNode = <Type size={14} />;
              let type: "String" | "Number" | "Time" = "String";
              if (field.field_type === "number") {
                icon = <Hash size={14} />;
                type = "Number";
              } else if (field.field_type === "time") {
                icon = <Clock3 size={14} />;
                type = "Time";
              }
              return {
                id: `${detail.id}-${field.field_name}`,
                name: field.field_name,
                type,
                knowledgeBase: kbLabel,
                updatedAt: field.updated_at || Date.now(),
                icon,
                isDefault: false
              };
            });
            availableMetadata = [...availableMetadata, ...customFields];
          }
        });
      }
    } catch (error) {
      console.error("Error loading metadata:", error);
    } finally {
      // 排序：自定义字段在前（按更新时间倒序），默认字段在底部
      availableMetadata.sort((a, b) => {
        if (a.isDefault && !b.isDefault) return 1;
        if (!a.isDefault && b.isDefault) return -1;
        if (!a.isDefault && !b.isDefault) return b.updatedAt - a.updatedAt;
        return a.name.localeCompare(b.name);
      });

      setAvailableMetadataState(availableMetadata);
      setIsLoadingMetadata(false);
      
      // 元数据加载完成后，验证现有条件
      if (conditions.length > 0) {
        validateAllConditions();
      }
    }
  };

  // 监听节点变化
  useEffect(() => {
    const currentIds = JSON.stringify(selectedKnowledgeIds());
    if (currentIds !== knowledgeIdsStr) {
      setKnowledgeIdsStr(currentIds);
      if (isEnabled) {
        console.log("检测到节点变化，重新获取元数据");
        fetchAndPrepareMetadata();
      }
    }
  }, [selectedKnowledgeIds(), isEnabled]);

  // 监听启用状态变化
  useEffect(() => {
    if (isEnabled) {
      fetchAndPrepareMetadata();
    }
  }, [isEnabled]);

  // 监听外部数据变化
  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false;
      return;
    }

    if (data.value && !isUpdatingFromExternal.current) {
      isUpdatingFromExternal.current = true;

      setIsEnabled(data.value.enabled ?? false);

      if (data.value.operator === "or") {
        setRelation("or");
      } else {
        setRelation("and");
      }

      if (data.value.conditions && Array.isArray(data.value.conditions)) {
        const newConditions = data.value.conditions.map(cond => ({
          id: cond.id || generateUUID(8),
          metadataField: cond.knowledge_id && cond.metadata_field
            ? `${cond.knowledge_id}-${cond.metadata_field}`
            : "",
          operator: cond.comparison_operation || "",
          valueType: cond.right_value_type === "ref" ? "reference" : "input",
          value: cond.right_value || "",
        }));
        setConditions(newConditions);
      }

      // 延迟重置标志，避免循环
      setTimeout(() => {
        isUpdatingFromExternal.current = false;
      }, 100);
    }
  }, [data.value]);

  // 监听内部状态变化并更新外部
  useEffect(() => {
    if (isUpdatingFromExternal.current) return;

    if (isEnabled) {
      validateConditions();
      const filterData = {
        enabled: true,
        operator: relation,
        conditions: conditions.map(cond => {
          const [knowledgeId, ...fieldParts] = cond.metadataField.split("-");
          const metadata_field = fieldParts.join("-");
          return {
            id: cond.id,
            knowledge_id: knowledgeId ? parseInt(knowledgeId, 10) : 0,
            metadata_field: metadata_field || "",
            comparison_operation: cond.operator,
            right_value_type: cond.valueType === "reference" ? "ref" : "input",
            right_value: cond.value,
          };
        }),
      };
      const currentDataStr = JSON.stringify(filterData);
      const prevDataStr = JSON.stringify(data.value);

      if (currentDataStr !== prevDataStr) {
        onChange(filterData);
      }
    } else {
      onChange({ enabled: false });
      onValidate(() => false);
    }
  }, [conditions, relation, isEnabled, onChange]);

  // 组件卸载时清理
  useEffect(() => {
    return () => {
      if (validateTimer.current) {
        clearTimeout(validateTimer.current);
      }
    };
  }, []);

  // 变量校验函数
  const validateMetadataField = useCallback((metadataFieldId: string, fieldName: string = ""): string => {
    if (!metadataFieldId) return "";
    
    // 检查选择的元数据字段是否在可用列表中
    const isValid = availableMetadataState.some(meta => meta.id === metadataFieldId);
    
    if (!isValid) {
      // 使用 isVarInFlow 函数进行详细校验
      const errorMsg = isVarInFlow(nodeId, flow.nodes, metadataFieldId, fieldName);
      return errorMsg || "选择的元数据字段无效或已被删除";
    }
    
    return "";
  }, [availableMetadataState, flow.nodes, nodeId]);

  // 实时校验所有条件
  const validateAllConditions = useCallback(() => {
    const errors: { [key: string]: string } = {};
    
    conditions.forEach(condition => {
      if (condition.metadataField) {
        const selectedMeta = availableMetadataState.find(m => m.id === condition.metadataField);
        const fieldName = selectedMeta ? `${selectedMeta.knowledgeBase}/${selectedMeta.name}` : "";
        const error = validateMetadataField(condition.metadataField, fieldName);
        
        if (error) {
          errors[condition.id] = error;
        }
      }
    });
    
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  }, [conditions, availableMetadataState, validateMetadataField]);

  // 在条件更新时自动校验
  useEffect(() => {
    if (conditions.length > 0 && availableMetadataState.length > 0) {
      validateAllConditions();
    }
  }, [conditions, availableMetadataState]);

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

        // 清除相关错误
        setFieldErrors(prevErrors => ({
          ...prevErrors,
          [id]: ""
        }));

        if (field === "metadataField") {
          // 实时校验元数据字段
          const selectedMeta = availableMetadataState.find(m => m.id === value);
          const fieldName = selectedMeta ? `${selectedMeta.knowledgeBase}/${selectedMeta.name}` : "";
          const errorMsg = validateMetadataField(value, fieldName);
          
          if (errorMsg) {
            setFieldErrors(prevErrors => ({
              ...prevErrors,
              [id]: errorMsg
            }));
          } else {
            updated.operator = "";
            updated.value = "";
            updated.valueType = "input";
            
            // 当选择 Number 类型的元数据字段时，自动设置默认值为 "0"
            if (selectedMeta?.type === "Number") {
              updated.value = "0";
            }
          }
        }

        if (field === "operator" && ["empty", "not_empty"].includes(value)) {
          updated.value = "";
        }

        if (field === "valueType") {
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
    const isValid = conditions.every(cond => {
      if (!cond.metadataField || !cond.operator) {
        return false;
      }

      // 校验元数据字段有效性
      if (cond.metadataField && !validateMetadataField(cond.metadataField)) {
        return false;
      }

      // 如果操作符是 empty 或 not_empty，不需要校验值
      if (['empty', 'not_empty'].includes(cond.operator)) {
        return true;
      }

      // 对于 Time 类型，允许值为空
      const metadataType = getConditionMetadataType(cond.id);
      if (metadataType === "Time") {
        return true;
      }

      // 对于 Number 类型，"0" 是有效值
      if (metadataType === "Number") {
        const isValidNumber = cond.value !== "" && cond.value !== null && cond.value !== undefined;
        return isValidNumber;
      }

      // String 类型需要非空值
      return !!cond.value;
    });

    const validateFunc = () => {
      const errors = [];

      conditions.forEach((cond, index) => {
        if (!cond.metadataField) {
          errors.push(`条件 ${index + 1}: 请选择元数据字段`);
        } else if (validateMetadataField(cond.metadataField)) {
          errors.push(`条件 ${index + 1}: 选择的元数据字段无效或已被删除`);
        }
        if (!cond.operator) {
          errors.push(`条件 ${index + 1}: 请选择操作符`);
        }
        if (!['empty', 'not_empty'].includes(cond.operator)) {
          const metadataType = getConditionMetadataType(cond.id);
          if (metadataType === "Number") {
            // Number 类型：空值、null、undefined 才报错，"0" 是有效值
            if (cond.value === "" || cond.value === null || cond.value === undefined) {
              errors.push(`条件 ${index + 1}: 请输入值`);
            }
          } else if (metadataType !== "Time" && !cond.value) {
            // String 类型需要非空值
            errors.push(`条件 ${index + 1}: 请输入值`);
          }
        }
      });

      return errors.length > 0 ? errors.join('; ') : false;
    };

    onValidate(validateFunc);
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
      const selectedLabel = condition.value
        ? condition.value.split('.').reduce((acc, part, index, array) => {
          return index === array.length - 1 ? `${acc}/${part}` : `${acc}.${part}`;
        })
        : "";

      return (
        <div className="flex items-center gap-1 min-w-0">
          <SelectVar
            className="max-w-40 flex-1"
            nodeId={nodeId}
            itemKey={condition.id}
            onSelect={(E: any, v: any) => {
              const selectedValue = `${E.name}.${v.value}`;
              updateCondition(condition.id, "value", selectedValue);
            }}
          >
            <div
              className={`no-drag nowheel group flex h-8 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-search-input px-3 py-1 text-sm shadow-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1 data-[placeholder]:text-gray-400`}
            >
              <span className="flex items-center flex-1 truncate">{selectedLabel || "请选择"}</span>
              <ChevronDown className="h-5 w-5 min-w-5 opacity-80 group-data-[state=open]:rotate-180" />
            </div>
          </SelectVar>
        </div>
      );
    }
    if (metadataType === "String") {
      return (
        <Input
          placeholder={condition.operator === "regex" ? "输入正则表达式" : "输入值"}
          value={condition.value}
          onChange={(e) => updateCondition(condition.id, "value", e.target.value)}
          maxLength={255}
          className="h-8"
        />
      );
    }
    if (metadataType === "Number") {
      return (
        <div className="w-full mt-2">
          <NumberInput
            value={condition.value || ''}
            onChange={(value) => {
              updateCondition(condition.id, "value", value);
            }}
          />
        </div>
      );
    }
    if (metadataType === "Time") {
      return (
        <DatePicker
          value={condition.value ? new Date(condition.value) : undefined}
          placeholder="选择时间"
          showTime
          onChange={(d) => updateCondition(condition.id, "value", d ? format(d, "yyyy-MM-dd'T'HH:mm:ss") : "")}
        />
      );
    }
    return (
      <Input
        placeholder="输入值"
        value={condition.value}
        onChange={(e) => updateCondition(condition.id, "value", e.target.value)}
        className="h-8"
      />
    );
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
                  <Badge variant="outline" className="absolute top-1/2 left-0.5 -translate-x-1/2 -translate-y-1/2 px-1 py-0 text-primary bg-[#E6ECF6] cursor-pointer z-10" onClick={handleRelationChange}>
                    {relation} <RefreshCcw size={12} />
                  </Badge>
                </div>
              </div>
            )}
            {conditions.map((condition) => {
              const metadataType = getConditionMetadataType(condition.id);
              const isTimeType = metadataType === "Time";
              const selectedMeta = availableMetadataState.find(m => m.id === condition.metadataField);
              const fieldName = selectedMeta ? `${selectedMeta.knowledgeBase}/${selectedMeta.name}` : "";

              return (
                <div key={condition.id} className="relative group pl-10 nodrag">
                  <div className="flex gap-2 items-center min-w-0">
                    <div className={`flex-1 min-w-0 ${isTimeType ? 'max-w-[15%]' : 'max-w-[25%]'}`}>
                      <Select
                        value={condition.metadataField}
                        onValueChange={(value) => updateCondition(condition.id, "metadataField", value)}
                        onOpenChange={setIsSelectOpen}
                      >
                        <SelectTrigger className="h-8 min-w-0">
                          <SelectValue placeholder="选择变量">
                            {condition.metadataField && (
                              <TooltipProvider>
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <div className="flex items-center gap-1" style={{ pointerEvents: 'auto' }}>
                                      {selectedMeta?.icon || null}
                                      <span style={{
                                        flex: 1,
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        whiteSpace: 'nowrap',
                                      }}>
                                        {fieldName || '选择变量'}
                                      </span>
                                    </div>
                                  </TooltipTrigger>
                                  <TooltipContent className="max-w-[200px] break-words">
                                    <p className="text-xs">{fieldName}</p>
                                  </TooltipContent>
                                </Tooltip>
                              </TooltipProvider>
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
                                    <Search className="absolute left-3 top-2 h-3 w-3 text-muted-foreground" />
                                    <input
                                      type="text"
                                      placeholder="搜索元数据"
                                      className="w-full pl-8 pr-2 py-1 text-[12px] border rounded"
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
                                      className="pr-2 w-full max-w-[240px]"
                                    >
                                      <div className="flex items-center justify-between w-full gap-1 min-w-0">
                                        <div className="flex items-center gap-1 min-w-0 flex-1">
                                          <span className="flex-shrink-0 text-xs">{meta.icon}</span>
                                          <span className="text-xs text-muted-foreground flex-shrink-0">{meta.type}</span>
                                          <TooltipProvider>
                                            <Tooltip>
                                              <TooltipTrigger asChild>
                                                <span className="truncate text-xs min-w-0 flex-1">
                                                  {meta.name}
                                                </span>
                                              </TooltipTrigger>
                                              <TooltipContent className="max-w-[200px] break-words">
                                                <p className="text-xs">{meta.name}</p>
                                              </TooltipContent>
                                            </Tooltip>
                                          </TooltipProvider>
                                        </div>
                                        <TooltipProvider>
                                          <Tooltip>
                                            <TooltipTrigger asChild>
                                              <span className="text-xs text-gray-500 truncate max-w-[60px] text-right flex-shrink-0 ml-1">
                                                {meta.knowledgeBase}
                                              </span>
                                            </TooltipTrigger>
                                            <TooltipContent className="max-w-[200px] break-words">
                                              <p className="text-xs">{meta.knowledgeBase}</p>
                                            </TooltipContent>
                                          </Tooltip>
                                        </TooltipProvider>
                                      </div>
                                    </SelectItem>
                                  ))
                                ) : (
                                  <div className="p-2 text-center text-xs text-gray-500">
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
                        <SelectTrigger className="h-8 min-w-0">
                          <SelectValue placeholder="选择条件" />
                        </SelectTrigger>
                        <SelectContent>
                          {metadataType && operatorConfig[metadataType].map((op) => (
                            <SelectItem key={op} value={op}>{operatorLabels[op]}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    {!["empty", "not_empty"].includes(condition.operator) &&
                      <>
                        <div className={`flex-1 min-w-0 ${isTimeType ? 'max-w-[16%]' : 'max-w-[20%]'}`}>
                          <Select
                            value={condition.valueType}
                            onValueChange={(value: "reference" | "input") => updateCondition(condition.id, "valueType", value)}
                          >
                            <SelectTrigger className="h-8 min-w-0">
                              <div className="flex items-center justify-between w-full">
                                <span>
                                  {condition.valueType === "reference" ? "引用" : "输入"}
                                </span>
                                {condition.valueType === "reference" && metadataType === "Time" && (
                                  <div className="relative group/info flex-shrink-0">
                                    <CircleQuestionMark size={16} className="text-gray-400" />
                                    <div className="absolute bottom-full right-0 mb-2 hidden group-hover/info:block p-2 bg-black text-white text-xs rounded z-10">
                                      引用变量请调整格式为"YYYY-MM-DD HH:mm:ss"，如"2025-01-10T21:08:20"表示2025年1月10日21时08分20秒
                                    </div>
                                  </div>
                                )}
                              </div>
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="reference">引用</SelectItem>
                              <SelectItem value="input">输入</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                        <div className={`flex-1 min-w-0 ${isTimeType ? 'max-w-[45%]' : 'max-w-[25%]'}`}>
                          {renderValueInput(condition)}
                        </div>
                      </>
                    }

                    <div className={`flex-shrink-0 ${isTimeType ? 'max-w-[10%]' : 'max-w-[10%]'} flex justify-center`}>
                      <Trash2
                        size={18}
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