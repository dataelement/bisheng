import { Checkbox } from "@/components/bs-ui/checkBox";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { locationContext } from "@/contexts/locationContext";
import { useContext, useMemo, useEffect, useState, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import FileUploadSplitStrategy from "./FileUploadSplitStrategy";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { cn } from "@/utils";

// 工具函数：将1/0或布尔值转为标准布尔值
const toBoolean = (value) => {
  if (value === undefined || value === null) return false;
  if (typeof value === "number") return value === 1;
  if (typeof value === "string") return value.toLowerCase() === "true";
  return Boolean(value);
};

// 工具函数：驼峰转下划线
const camelToSnake = (str) => {
  return str.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);
};

// 生成稳定的策略ID（基于内容哈希）
const getStrategyId = (regexStr, position) => {
  let hash = 0;
  const str = `${regexStr}-${position}`;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash) + str.charCodeAt(i);
    hash = hash & hash;
  }
  return `strategy-${Math.abs(hash)}`;
};

export default function RuleFile({
  rules,
  setRules,
  strategies = [],
  setStrategies = () => {},
  originalSplitRule,
  setOriginalSplitRule = () => {},
  isAdjustMode = false,
  showPreview =false
}) {
  console.log(showPreview,199);
  
  const { appConfig } = useContext(locationContext);
  const { t } = useTranslation('knowledge');

  // 安全解析 originalSplitRule
  const parsedOriginalSplitRule = useMemo(() => {
    if (!originalSplitRule) return {};
    if (typeof originalSplitRule === 'string') {
      try {
        const parsed = JSON.parse(originalSplitRule);
        return typeof parsed === 'object' && parsed !== null ? parsed : {};
      } catch (e) {
        console.error('解析 originalSplitRule 失败:', e);
        return {};
      }
    }
    return typeof originalSplitRule === 'object' ? { ...originalSplitRule } : {};
  }, [originalSplitRule]);

  // 计算当前值
  const currentRules = useMemo(() => {
    const baseRules = isAdjustMode ? parsedOriginalSplitRule : { ...rules };
    
    return {
      chunkSize: String(baseRules.chunk_size ?? baseRules.chunkSize ?? "1000"),
      chunkOverlap: String(baseRules.chunk_overlap ?? baseRules.chunkOverlap ?? "0"),
      retainImages: toBoolean(baseRules.retain_images ?? baseRules.retainImages),
      forceOcr: toBoolean(baseRules.force_ocr ?? baseRules.forceOcr),
      enableFormula: toBoolean(baseRules.enable_formula ?? baseRules.enableFormula),
    };
  }, [isAdjustMode, parsedOriginalSplitRule, rules]);

  // 内部状态与外部状态同步
  const [internalValues, setInternalValues] = useState(currentRules);
  const prevRulesRef = useRef(currentRules);

  useEffect(() => {
    if (JSON.stringify(prevRulesRef.current) !== JSON.stringify(currentRules)) {
      setInternalValues(currentRules);
      prevRulesRef.current = currentRules;
    }
  }, [currentRules]);

  // 使用 useEffect 监听 originalSplitRule 的变化
  useEffect(() => {
    console.log('originalSplitRule 已更新:', originalSplitRule);
  }, [originalSplitRule]);

  // 策略初始化
  const hasInitialized = useRef(false);
  useEffect(() => {
    if (!isAdjustMode || hasInitialized.current) return;
    
    const validSeparatorPairs = (parsedOriginalSplitRule.separator || [])
      .map((regexStr, index) => ({
        regexStr: String(regexStr || '').trim(),
        position: (parsedOriginalSplitRule.separator_rule || [])[index] || 'after'
      }))
      .filter(pair => pair.regexStr);

    if (validSeparatorPairs.length > 0) {
      const regexToRuleMap = {
        '\\n': '单换行后切分，用于分隔普通换行',
        '\\n\\n': '双换行后切分,用于分隔段落',
        '第.{1,3}章': '"第X章"前切分，切分章节等',
        '第.{1,3}条': '"第X条"前切分，切分条目等',
        '。': '中文句号后切分，中文断句',
        '\\.': '英文句号后切分，英文断句'
      };

      const convertedStrategies = validSeparatorPairs.map((pair) => ({
        id: getStrategyId(pair.regexStr, pair.position),
        regex: pair.regexStr,
        position: pair.position,
        rule: regexToRuleMap[pair.regexStr] || `自定义规则: ${pair.regexStr}`
      }));

      setStrategies(convertedStrategies);
    }

    hasInitialized.current = true;
  }, [isAdjustMode, parsedOriginalSplitRule, setStrategies]);

  // 修复核心：处理输入框和勾选框的值变化
  const handleSettingChange = useCallback((key, value) => {
    let rawValue;
    if (value?.target?.type === 'checkbox') {
      rawValue = value.target.checked;
    } else if (value?.target?.value !== undefined) {
      rawValue = value.target.value;
    } else {
      rawValue = value;
    }

    // 更新UI
    setInternalValues(prev => ({ ...prev, [key]: rawValue }));

     if (isAdjustMode) {
    const snakeKey = camelToSnake(key);
    
    let storedValue;
    if (typeof rawValue === 'boolean') {
      storedValue = rawValue;
    } else if (key === 'chunkSize' || key === 'chunkOverlap') {
      storedValue = rawValue === '' ? (key === 'chunkSize' ? 1000 : 0) : Number(rawValue);
    } else {
      storedValue = rawValue;
    }

    // 直接更新原始分割规则
    setOriginalSplitRule(prev => {
      const current = typeof prev === 'string' 
        ? (() => { try { return JSON.parse(prev); } catch { return {}; } })()
        : (prev || {});
      
      const updated = { ...current, [snakeKey]: storedValue };
      console.log('更新后的值:', updated);
      return updated; // 确保返回更新后的对象
    });
  } else {
    setRules(prev => ({ ...(prev || {}), [key]: rawValue }));
  }
}, [isAdjustMode, setOriginalSplitRule, setRules]);

  // 策略变化处理
  const handleStrategiesChange = useCallback((newStrategies) => {
    setStrategies(newStrategies);
    
    if (isAdjustMode) {
      const separator = newStrategies.map(s => s.regex);
      const separatorRule = newStrategies.map(s => s.position);
      
      setOriginalSplitRule(prev => {
        const current = typeof prev === 'string' 
          ? (() => { try { return JSON.parse(prev); } catch { return {}; } })()
          : (prev || {});
        return { ...current, separator, separator_rule: separatorRule };
      });
    }
  }, [isAdjustMode, setOriginalSplitRule, setStrategies]);

  return (
    <div className="flex-1 flex flex-col relative max-w-[760px] mx-auto">
      <div className="flex flex-col gap-4 mt-9" style={{ gridTemplateColumns: '114px 1fr' }}>
        <div className="space-y-4 p-4 border rounded-lg">
          <h3 className="font-bold text-gray-800 text-left text-md">{t('splitSettings')}</h3>

          <div className="flex gap-4">
            {/* 核心修改：根据showPreview调整间距 */}
            <div className={cn("w-1/2 flex items-center", showPreview ? "gap-0" : "gap-3")}>
              <Label htmlFor="splitLength"className={cn("whitespace-nowrap text-sm min-w-[100px]", showPreview ? "-mr-4" : "")}>
                {t('splitLength')}
              </Label>
              <div className={cn('relative', showPreview ? "pl-2" : "")}>
                <Input
                  id="splitLength"
                  type="number"
                  step="100"
                  min={0}
                  value={internalValues.chunkSize}
                  onChange={(e) => handleSettingChange('chunkSize', e)}
                  placeholder={t('splitSizePlaceholder')}
                  className="flex-1 min-w-[150px]"
                  onBlur={(e) => {
                    if (!e.target.value) {
                      handleSettingChange('chunkSize', { target: { value: '1000' } });
                    }
                  }}
                />
                <span className="absolute right-8 top-1/2 -translate-y-1/2 text-gray-400">字符</span>
              </div>
            </div>

            {/* 核心修改：根据showPreview调整间距 */}
            <div className={cn("w-1/2 flex items-center", showPreview ? "gap-0" : "gap-3")}>
              <Label htmlFor="chunkOverlap" className={cn("whitespace-nowrap text-sm min-w-[100px]", showPreview ? "-mr-5" : "")}>
                {t('chunkOverlap')}
              </Label>
              <div className="relative">
                <Input
                  id="chunkOverlap"
                  type="number"
                  step="10"
                  min={0}
                  value={internalValues.chunkOverlap}
                  onChange={(e) => handleSettingChange('chunkOverlap', e)}
                  placeholder={t('chunkOverlapPlaceholder')}
                  className="flex-1 min-w-[150px]"
                  onBlur={(e) => {
                    if (!e.target.value) {
                      handleSettingChange('chunkOverlap', { target: { value: '0' } });
                    }
                  }}
                />
                <span className="absolute right-8 top-1/2 -translate-y-1/2 text-gray-400">字符</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 pt-2">
            <Checkbox
              id="retainImages"
              checked={internalValues.retainImages}
              onCheckedChange={(e) => handleSettingChange('retainImages', e)}
            />
            <Label htmlFor="retainImages" className="text-sm text-gray-700 flex items-center">
              {t('keepImages')}
              <QuestionTooltip content="解析时将保留文档中的图片内容， 以支持问答时图文并茂的回复。" />
            </Label>
          </div>
        </div>

        <div className="p-4 border rounded-lg">
          <Label htmlFor="splitMethod" className="flex justify-start text-md text-left font-bold text-gray-800">
            {t('splitMethod')}
          </Label>
          <FileUploadSplitStrategy data={strategies} onChange={handleStrategiesChange} />
        </div>

        {appConfig.enableEtl4lm && (
          <div className="space-y-4 p-4 border rounded-lg">
            <h3 className="text-md font-bold text-gray-800 text-left ">{t('pdfAnalysis')}</h3>
            <div className="flex items-center gap-2 pt-2">
              <Checkbox
                id="forceOcr"
                checked={internalValues.forceOcr}
                onCheckedChange={(e) => handleSettingChange('forceOcr', e)}
              />
              <Label htmlFor="forceOcr" className="text-sm text-gray-700">{t('ocrForce')}</Label>
              <Checkbox
                id="enableFormula"
                checked={internalValues.enableFormula}
                onCheckedChange={(e) => handleSettingChange('enableFormula', e)}
              />
              <Label htmlFor="enableFormula" className="text-sm text-gray-700">{t('enableRec')}</Label>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}