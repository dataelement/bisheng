// @ts-strict-ignore
import { Button, Select, type SelectOption } from '@bisheng/ui';

import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { generateUUID } from "@/components/bs-ui/utils";
import { getKnowledgeDetailApi } from "@/controllers/API";
import { Tooltip as SharedTooltip,Switch } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { Hash,Type } from "lucide-react";
import { useCallback,useEffect,useLayoutEffect,useMemo,useRef,useState } from "react";
import { useTranslation } from "react-i18next";
import { MetadataValueInput } from "./MetadataValueInput";
export interface MetadataCondition {
  id: string;
  metadataField: string;
  operator: string;
  valueType: "reference" | "input";
  value: string;
  valueLabel: string;
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
type KnowledgeSelectionType = "knowledge" | "space" | "tmp";
interface KnowledgeSelectionItem {
  id: string;
  label: string;
}
interface KnowledgeSelection {
  type: KnowledgeSelectionType;
  items: KnowledgeSelectionItem[];
}
interface DefaultMetadataFieldDefinition {
  name: string;
  type: "String" | "Number" | "Time";
  icon: "text" | "number" | "time";
}
const DEFAULT_METADATA_FIELDS: DefaultMetadataFieldDefinition[] = [
  { name: "document_id", type: "Number", icon: "number" },
  { name: "document_name", type: "String", icon: "text" },
  { name: "upload_time", type: "Time", icon: "time" },
  { name: "update_time", type: "Time", icon: "time" },
  { name: "uploader", type: "String", icon: "text" },
  { name: "updater", type: "String", icon: "text" },
];
interface MetadataFilterProps {
  data: any;
  onChange: (value: any) => void;
  onValidate: (validate: any) => void;
  selectedKnowledgeIds?: () => string[];
  nodeId?: string;
  node?: any;
  onVarEvent?: (validateFunc: () => Promise<string>) => void;
  i18nPrefix: string
}
const MetadataFilter = ({
  data,
  onChange,
  onValidate,
  selectedKnowledgeIds = () => [],
  nodeId,
  node,
  onVarEvent,
  i18nPrefix
}: MetadataFilterProps) => {
  const isInitialMount = useRef(true);
  const isUpdatingFromExternal = useRef(false);
  const { t } = useTranslation('flow')
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
        valueLabel: cond.right_label || "",
      }));
    }
    return [];
  });
  const [relation, setRelation] = useState<"and" | "or">(() => {
    return data.value?.operator === "or" ? "or" : "and";
  });
  const [required, setRequired] = useState(false);
  const [availableMetadataState, setAvailableMetadataState] = useState<MetadataField[]>([]);
  const [isLoadingMetadata, setIsLoadingMetadata] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<{ [key: string]: string }>({});
  const [error, setError] = useState(false)
  // 用 ref 存储最新状态，绕开闭包问题
  const stateRef = useRef({
    conditions: conditions,
    availableMetadataState: availableMetadataState,
    isLoadingMetadata: isLoadingMetadata
  });
  // 状态变化时同步更新 ref
  useEffect(() => {
    stateRef.current = {
      conditions,
      availableMetadataState,
      isLoadingMetadata
    };
  }, [conditions, availableMetadataState, isLoadingMetadata]);
  const knowledgeParam = node?.group_params
    ?.flatMap(group => group.params || [])
    .find(param => param.type === "knowledge_select_multi");
  const knowledgeValue = knowledgeParam?.value;
  const knowledgeType: KnowledgeSelectionType = knowledgeValue?.type === "space"
    ? "space"
    : knowledgeValue?.type === "tmp"
      ? "tmp"
      : "knowledge";
  const knowledgeItems: KnowledgeSelectionItem[] = Array.isArray(knowledgeValue?.value)
    ? knowledgeValue.value.map(item => ({ id: String(item.key), label: item.label || "" }))
    : selectedKnowledgeIds().map(id => ({ id: String(id), label: "" }));
  const knowledgeSelectionKey = JSON.stringify({ type: knowledgeType, items: knowledgeItems });
  const operatorConfig = {
    String: ["equals", "not_equals", "contains", "not_contains", "is_empty", "is_not_empty", "starts_with", "ends_with"],
    Number: ["equals", "not_equals", "greater_than", "less_than", "greater_than_or_equal", "less_than_or_equal"],
    Time: ["equals", "not_equals", "is_empty", "is_not_empty", "greater_than", "less_than", "greater_than_or_equal", "less_than_or_equal"],
  };
  const operatorLabels = {
    equals: t('equals'),
    not_equals: t('notEquals'),
    contains: t('contains'),
    not_contains: t('notContains'),
    is_empty: t('isEmpty'),
    is_not_empty: t('isNotEmpty'),
    starts_with: t('startsWith'),
    ends_with: t('endsWith'),
    regex: t('regex'),
    greater_than: ">",
    less_than: "<",
    greater_than_or_equal: "≥",
    less_than_or_equal: "≤",
  };
  const fetchAndPrepareMetadata = useCallback(async (selection: KnowledgeSelection) => {
    let availableMetadata: MetadataField[] = [];
    try {
      let knowledgeDetails: any[] = [];
      if (selection.type === "space") {
        knowledgeDetails = selection.items.map(item => ({
          id: item.id,
          label: item.label,
          metadata_fields: [],
        }));
      } else if (selection.type === "knowledge" && selection.items.length > 0) {
        knowledgeDetails = await getKnowledgeDetailApi(selection.items.map(item => item.id));
      }
      if (knowledgeDetails.length > 0) {
        knowledgeDetails.forEach((detail: any) => {
          const kbLabel = detail.name || detail.label || t('unknownKnowledgeBase');
          const defaultMetadataFields = DEFAULT_METADATA_FIELDS.map(field => ({
            id: `${detail.id}-${field.name}`,
            name: field.name,
            type: field.type,
            knowledgeBase: kbLabel,
            updatedAt: Date.now(),
            icon: field.icon === "number"
              ? <Hash size={14} />
              : field.icon === "time"
                ? <Outlined.Time size={14} />
                : <Type size={14} />,
            isDefault: true
          }));
          availableMetadata = [...availableMetadata, ...defaultMetadataFields];
          if (selection.type === "knowledge" && detail.metadata_fields && Array.isArray(detail.metadata_fields)) {
            const customFields = detail.metadata_fields.map((field: any) => {
              let icon: React.ReactNode = <Type size={14} />;
              let type: "String" | "Number" | "Time" = "String";
              if (field.field_type === "number") {
                icon = <Hash size={14} />;
                type = "Number";
              } else if (field.field_type === "time") {
                icon = <Outlined.Time size={14} />;
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
    }
    availableMetadata.sort((a, b) => {
      if (a.isDefault && !b.isDefault) return 1;
      if (!a.isDefault && b.isDefault) return -1;
      if (!a.isDefault && !b.isDefault) return a.updatedAt - b.updatedAt;
      return a.name.localeCompare(b.name);
    });
    return availableMetadata;
  }, [t]);
  useEffect(() => {
    let ignoreResult = false;
    if (!isEnabled) {
      setIsLoadingMetadata(false);
      return;
    }
    setIsLoadingMetadata(true);
    const selection = JSON.parse(knowledgeSelectionKey) as KnowledgeSelection;
    fetchAndPrepareMetadata(selection).then((availableMetadata) => {
      if (ignoreResult) return;
      setAvailableMetadataState(availableMetadata);
      setIsLoadingMetadata(false);
    });
    return () => {
      ignoreResult = true;
    };
  }, [isEnabled, knowledgeSelectionKey, fetchAndPrepareMetadata]);
  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false;
      if (data.value) {
        setIsEnabled(data.value.enabled ?? false);
        setRelation(data.value.operator === "or" ? "or" : "and");
        if (data.value.conditions && Array.isArray(data.value.conditions)) {
          const newConditions = data.value.conditions.map(cond => ({
            id: cond.id || generateUUID(8),
            metadataField: cond.knowledge_id && cond.metadata_field
              ? `${cond.knowledge_id}-${cond.metadata_field}`
              : "",
            operator: cond.comparison_operation || "",
            valueType: cond.right_value_type === "ref" ? "reference" : "input",
            value: cond.right_value || "",
            valueLabel: cond.right_label || "",
          }));
          setConditions(newConditions);
        }
      }
      // 初始挂载立即校验
      checkAllFieldsValidity();
      validateConditionsUI();
      onValidate(validateFunc);
      return;
    }
    if (isUpdatingFromExternal.current) {
      queueMicrotask(() => {
        isUpdatingFromExternal.current = false;
      });
      return;
    }
  }, [data.value]);
  // 校验函数直接从 ref 拿最新状态
  const checkAllFieldsValidity = useCallback(() => {
    const { conditions, availableMetadataState, isLoadingMetadata } = stateRef.current;
    if (isLoadingMetadata) return;
    const newFieldErrors = { ...fieldErrors };
    conditions.forEach(cond => {
      if (!cond.metadataField) {
        if (newFieldErrors[cond.id]) delete newFieldErrors[cond.id];
        return;
      }
      const isFieldValid = availableMetadataState.some(meta => meta.id === cond.metadataField);
      if (!isFieldValid) {
        newFieldErrors[cond.id] = t('invalidOrDeletedMetadataField');
      } else if (newFieldErrors[cond.id] === t('invalidOrDeletedMetadataField')) {
        delete newFieldErrors[cond.id];
      }
    });
    if (JSON.stringify(newFieldErrors) !== JSON.stringify(fieldErrors)) {
      setFieldErrors(newFieldErrors);
    }
  }, [fieldErrors]);
  // validateFunc 从 ref 拿最新 conditions
  const validateFunc = useCallback(() => {
    const { conditions, availableMetadataState } = stateRef.current;
    const errors = [];
    conditions.forEach((cond, index) => {
      if (!cond.metadataField) errors.push(t('selectMetadataField', { index: index + 1 }));
      if (!cond.operator) errors.push(t('selectOperator', { index: index + 1 }));
      // Real-time fetch of field type
      const meta = stateRef.current.availableMetadataState.find(m => m.id === cond.metadataField);
      if (meta?.type === "String" && cond.valueType !== "reference" && String(cond.value ?? "").length > 255) { errors.push(t("bs:sharedUi.maximum", { max: 255 })); }
      if (meta?.type === "Number" && !cond.valueLabel && cond.valueType === "reference") {
        errors.push(t('enterValue', { index: index + 1 }));
      }
    });
    return errors.length > 0 ? errors.join('; ') : false;
  }, []);
  const validateConditionsUI = useCallback(() => {
    const { conditions } = stateRef.current;
    const isValid = conditions.every(cond => {
      if (!cond.metadataField || !cond.operator) return false;
      if ([`is_empty`, `is_not_empty`].includes(cond.operator)) return true;
      const meta = stateRef.current.availableMetadataState.find(m => m.id === cond.metadataField);
      if (meta?.type === "String" && cond.valueType !== "reference" && String(cond.value ?? "").length > 255) return false;
      if (meta?.type === "Number") {
        return !!cond.value;
      }
      return true;
    });
    setRequired(!isValid);
    return isValid;
  }, []);
  useLayoutEffect(() => {
    if (!isEnabled) {
      onChange({ enabled: false });
      onValidate(() => false);
      return;
    }
    checkAllFieldsValidity();
    validateConditionsUI();
    onValidate(validateFunc);
    const filterData = {
      enabled: true,
      operator: relation,
      conditions: stateRef.current.conditions.map(cond => {
        const [knowledgeId, ...fieldParts] = cond.metadataField.split("-");
        const metadata_field = fieldParts.join("-");
        return {
          id: cond.id,
          knowledge_id: knowledgeId ? parseInt(knowledgeId, 10) : 0,
          metadata_field: metadata_field || "",
          comparison_operation: cond.operator,
          right_value_type: cond.valueType === "reference" ? "ref" : "input",
          right_value: cond.value,
          right_label: cond.valueLabel
        };
      }),
    };
    onChange(filterData);
  }, [isEnabled, relation, conditions, checkAllFieldsValidity, validateConditionsUI, validateFunc, onChange, onValidate]);
  const validateVars = useCallback(async (): Promise<string> => {
    if (!isEnabled) return "";
    try {
      const selection = JSON.parse(knowledgeSelectionKey) as KnowledgeSelection;
      if (selection.items.length === 0 || selection.type === "tmp") return "";
      const validFieldIds = new Set<string>();
      if (selection.type === "space") {
        selection.items.forEach(item => {
          DEFAULT_METADATA_FIELDS.forEach(field => {
            validFieldIds.add(`${item.id}-${field.name}`);
          });
        });
      } else {
        const knowledgeDetails = await getKnowledgeDetailApi(selection.items.map(item => item.id));
        knowledgeDetails.forEach((detail: any) => {
          DEFAULT_METADATA_FIELDS.forEach(field => {
            validFieldIds.add(`${detail.id}-${field.name}`);
          });
          if (detail.metadata_fields) {
            detail.metadata_fields.forEach((field: any) => {
              validFieldIds.add(`${detail.id}-${field.field_name}`);
            });
          }
        });
      }
      const { conditions } = stateRef.current;
      for (const condition of conditions) {
        if (!condition.metadataField) continue;
        if (!validFieldIds.has(condition.metadataField)) {
          setError(true)
          const fieldName = condition.metadataField.split("-").pop() || "";
          // 获取节点名称，如果没有则使用默认值
          const nodeName = node?.name || t('defaultNodeName');
          return `${nodeName} ${t('nodeError2', { fieldName })}`;
        }
      }
      setError(false)
      return "";
    } catch (error) {
      console.error("Error validating metadata fields:", error);
      return t('metadataFieldValidationError');
    }
  }, [isEnabled, knowledgeSelectionKey, node?.name, t]);
  useEffect(() => {
    if (onVarEvent) {
      onVarEvent(validateVars);
    }
    return () => {
      if (onVarEvent) {
        onVarEvent(() => Promise.resolve(""));
      }
    };
  }, [onVarEvent, validateVars]);
  const selectLabels = useSelectLabels();
  const metadataOptions = useMemo<SelectOption[]>(() => availableMetadataState
    .filter(meta => meta.id)
    .map(meta => ({
      value: meta.id,
      label: meta.name,
      icon: meta.icon,
      description: `${meta.type} · ${meta.knowledgeBase}`,
    })), [availableMetadataState]);
  // Old panel search matched the field name or its knowledge base name.
  const filterMetadataOption = useCallback((keyword: string, option: SelectOption) => {
    const term = keyword.toLowerCase().trim();
    const meta = availableMetadataState.find(m => m.id === option.value);
    return option.label.toLowerCase().includes(term)
      || (meta?.knowledgeBase || "").toLowerCase().includes(term);
  }, [availableMetadataState]);
  const valueTypeOptions = useMemo<SelectOption[]>(() => [
    { value: "reference", label: t('reference') },
    { value: "input", label: t('input') },
  ], [t]);
  const addCondition = () => {
    setConditions(prev => [...prev, {
      id: generateUUID(8),
      metadataField: "",
      operator: "",
      valueType: "input",
      value: "",
      valueLabel: ""
    }]);
  };
  const deleteCondition = (id: string) => {
    setConditions(prev => prev.filter(c => c.id !== id));
    // 立即清除错误，同时触发副作用校验
    setFieldErrors(prev => {
      const newErrors = { ...prev };
      delete newErrors[id];
      return newErrors;
    });
  };
  const updateCondition = (id: string, field: keyof MetadataCondition, value: string) => {
    setConditions(prev => {
      const newConditions = prev.map(condition => {
        if (condition.id === id) {
          let updated = { ...condition, [field]: value };
          if (field === "metadataField") {
            const selectedMeta = availableMetadataState.find(m => m.id === value);
            setFieldErrors(prev => {
              const newErrors = { ...prev };
              if (!selectedMeta && value) newErrors[id] = t('invalidOrDeletedMetadataField');
              else delete newErrors[id];
              return newErrors;
            });
            if (selectedMeta) {
              updated = {
                ...updated,
                operator: "",
                value: "",
                valueType: "input",
                valueLabel: ""
              };
              if (selectedMeta.type === "Number") updated.value = "0";
            }
          }
          if (field === "operator") {
            updated = {
              ...updated,
              value: "",
              valueLabel: ""
            };
          }
          if (field === "valueType") {
            updated = {
              ...updated,
              value: "",
              valueLabel: ""
            };
          }
          return updated;
        }
        return condition;
      });
      // 更新 stateRef
      stateRef.current.conditions = newConditions;
      return newConditions;
    });
  };
  const handleRelationChange = () => {
    setRelation(prev => prev === "and" ? "or" : "and");
  };
  return (<div className="space-y-4 rounded-lg min-w-0 mb-4">
      <div className="flex items-center justify-between min-w-0">
        <div className="flex items-center gap-2"><span className="text-sm font-medium text-gray-500">{t(`${i18nPrefix}label`)}</span></div>
        <Switch checked={isEnabled} onCheckedChange={setIsEnabled} />
      </div>
      {isEnabled && (
        <div className="space-y-3 min-w-0">
          <div className="space-y-2 min-w-0 relative">
            {conditions.length > 1 && (
              <div className="absolute left-1 top-0 w-4 h-full py-4">
                <div className="h-full border border-foreground border-dashed border-r-0 rounded-l-sm">
                  <Button size="small" variant="text" className="absolute top-1/2 left-0.5 -translate-x-1/2 -translate-y-1/2 px-1 py-0 text-primary cursor-pointer z-10" onClick={handleRelationChange} color="default">
                    {relation} <Outlined.Refresh size={12} />
                  </Button>
                </div>
              </div>
            )}
            {conditions.map((condition) => {
              const metadataType = stateRef.current.availableMetadataState.find(m => m.id === condition.metadataField)?.type;
              const isTimeType = metadataType === "Time";
              const hasError = !!fieldErrors[condition.id];
              const selectedMeta = stateRef.current.availableMetadataState.find(m => m.id === condition.metadataField);
              const displayName = selectedMeta ? selectedMeta.name : condition.metadataField.split("-").pop() || t('unknownField');
              const displayIcon = selectedMeta ? selectedMeta.icon : null;
              return (
                <div key={condition.id} className="relative group pl-10">
                  <div className="flex gap-2 items-center min-w-0">
                    <div className={`flex-1 min-w-0 ${isTimeType ? 'max-w-[15%]' : 'max-w-[25%]'}`}>
                      <SharedTooltip
                        content={hasError ? fieldErrors[condition.id] : displayName}
                        disabled={!condition.metadataField}
                      >
                        <div className="min-w-0">
                          <Select
                            {...selectLabels}
                            options={selectedMeta || !condition.metadataField
                              ? metadataOptions
                              // Keep a deleted / unknown field readable in the trigger.
                              : [...metadataOptions, { value: condition.metadataField, label: displayName }]}
                            value={condition.metadataField || null}
                            onChange={(value) => updateCondition(condition.id, "metadataField", value == null ? "" : String(value))}
                            placeholder={t('selectVariable')}
                            aria-label={t('selectVariable')}
                            showSearch
                            filterOption={filterMetadataOption}
                            loading={isLoadingMetadata}
                            loadingText={t('loadingMetadataFields')}
                            emptyText={t('noMetadataFields')}
                            noMatchText={t('noMetadataFields')}
                            status={error || hasError ? 'error' : 'default'}
                            className="nodrag w-full min-w-0"
                          />
                        </div>
                      </SharedTooltip>
                    </div>
                    <div className={`flex-1 min-w-0 ${isTimeType ? 'max-w-[15%]' : 'max-w-[20%]'}`}>
                      <Select
                        {...selectLabels}
                        options={metadataType ? operatorConfig[metadataType].map((op) => ({ value: op, label: operatorLabels[op] })) : []}
                        value={condition.operator || null}
                        onChange={(value) => updateCondition(condition.id, "operator", value == null ? "" : String(value))}
                        disabled={!condition.metadataField}
                        placeholder={t('selectCondition')}
                        aria-label={t('selectCondition')}
                        className="nodrag w-full min-w-0"
                      />
                    </div>
                    {
                      ![`is_empty`, `is_not_empty`].includes(condition.operator) && (
                        <>
                          <div className={`flex-1 min-w-0 ${isTimeType ? 'max-w-[16%]' : 'max-w-[20%]'}`}>
                            <div className="flex items-center gap-1 min-w-0">
                              <Select
                                {...selectLabels}
                                options={valueTypeOptions}
                                value={condition.valueType}
                                onChange={(value) => value != null && updateCondition(condition.id, "valueType", String(value))}
                                aria-label={t('valueType')}
                                className="nodrag flex-1 min-w-0"
                              />
                              {condition.valueType === "reference" && metadataType === "Time" && (
                                <SharedTooltip content={t('referenceFormatTip')}>
                                  <span className="flex-shrink-0" tabIndex={0}>
                                    <Outlined.Question size={16} className="text-gray-400" />
                                  </span>
                                </SharedTooltip>
                              )}
                            </div>
                          </div>
                          <div className={`flex-1 min-w-0 ${isTimeType ? 'max-w-[45%]' : 'max-w-[25%]'}`}>{<MetadataValueInput condition={condition} metadataType={stateRef.current.availableMetadataState.find(m => m.id === condition.metadataField)?.type} nodeId={nodeId} updateCondition={updateCondition} />}</div>
                        </>
                      )
                    }
                    <div className={`flex-shrink-0 ${isTimeType ? 'max-w-[10%]' : 'max-w-[10%]'} flex justify-center`}>
                      <Outlined.Delete size={18} onClick={() => deleteCondition(condition.id)} className="hover:text-red-600 cursor-pointer group-hover:opacity-100 opacity-0" />
                    </div>
                  </div >
                </div >
              );
            })}
          </div >
          <Button onClick={addCondition} variant="outlined" className="border-primary text-primary mt-2 h-8" color="default">{t('+ Add Condition')}</Button>
        </div >
      )}
    </div >
  );
};
export default MetadataFilter;
