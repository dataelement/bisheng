import { Checkbox } from "@/components/bs-ui/checkBox";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { locationContext } from "@/contexts/locationContext";
import { useContext, useMemo, useEffect, useState, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import FileUploadSplitStrategy from "./FileUploadSplitStrategy";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { cn } from "@/utils";
import { CircleHelp } from "lucide-react";

// Utility function: Convert 1/0 or boolean values to standard boolean
const toBoolean = (value) => {
  if (value === undefined || value === null) return false;
  if (typeof value === "number") return value === 1;
  if (typeof value === "string") return value.toLowerCase() === "true";
  return Boolean(value);
};

// Utility function: Convert camelCase to snake_case
const camelToSnake = (str) => {
  return str.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);
};

// Generate stable strategy ID (based on content hash)
const getStrategyId = (regexStr, position) => {
  let hash = 0;
  const str = `${regexStr}-${position}`;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash) + str.charCodeAt(i);
    hash = hash & hash;
  }
  return `strategy-${Math.abs(hash)}`;
};

interface RuleFileProps {
  rules: any;
  setRules: (updater: any) => void;
  strategies?: any[];
  setStrategies?: (newStrategies: any[]) => void;
  originalSplitRule?: any;
  setOriginalSplitRule?: (updater: any) => void;
  isAdjustMode?: boolean;
  showPreview?: boolean;
  isEtl4lm?: boolean;
}

export default function RuleFile({
  rules,
  setRules,
  strategies = [],
  setStrategies = () => {},
  originalSplitRule,
  setOriginalSplitRule = () => {},
  isAdjustMode = false,
  showPreview =false,
  isEtl4lm = false
}: RuleFileProps) {
  
  const { appConfig } = useContext(locationContext);
  const { t } = useTranslation('knowledge');

  // Safely parse originalSplitRule
  const parsedOriginalSplitRule = useMemo(() => {
    if (!originalSplitRule) return {};
    if (typeof originalSplitRule === 'string') {
      try {
        const parsed = JSON.parse(originalSplitRule);
        return typeof parsed === 'object' && parsed !== null ? parsed : {};
      } catch (e) {
        console.error('Failed to parse originalSplitRule:', e);
        return {};
      }
    }
    return typeof originalSplitRule === 'object' ? { ...originalSplitRule } : {};
  }, [originalSplitRule]);

  // Calculate current values
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

  // Internal state synchronization with external state
  const [internalValues, setInternalValues] = useState(currentRules);
  const prevRulesRef = useRef(currentRules);

  useEffect(() => {
    if (JSON.stringify(prevRulesRef.current) !== JSON.stringify(currentRules)) {
      setInternalValues(currentRules);
      prevRulesRef.current = currentRules;
    }
  }, [currentRules]);

  // Use useEffect to monitor changes in originalSplitRule
  useEffect(() => {
    console.log('originalSplitRule updated:', originalSplitRule);
  }, [originalSplitRule]);

  // Strategy initialization
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
        '\\n': t('singleNewlineRule'),
        '\\n\\n': t('doubleNewlineRule'),
        '第.{1,3}章': t('chapterRule'),
        '第.{1,3}条': t('articleRule'),
        '。': t('chinesePeriodRule'),
        '\\.': t('englishPeriodRule')
      };

      const convertedStrategies = validSeparatorPairs.map((pair) => ({
        id: getStrategyId(pair.regexStr, pair.position),
        regex: pair.regexStr,
        position: pair.position,
        rule: regexToRuleMap[pair.regexStr] || t('customRule', { regex: pair.regexStr })
      }));

      setStrategies(convertedStrategies);
    }

    hasInitialized.current = true;
  }, [isAdjustMode, parsedOriginalSplitRule, setStrategies, t]);

  // Core fix: Handle input box and checkbox value changes
  const handleSettingChange = useCallback((key, value) => {
    let rawValue;
    if (value?.target?.type === 'checkbox') {
      rawValue = value.target.checked;
    } else if (value?.target?.value !== undefined) {
      rawValue = value.target.value;
    } else {
      rawValue = value;
    }

    // Update UI
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

    // Directly update original split rule
    setOriginalSplitRule(prev => {
      const current = typeof prev === 'string' 
        ? (() => { try { return JSON.parse(prev); } catch { return {}; } })()
        : (prev || {});
      
      const updated = { ...current, [snakeKey]: storedValue };
      console.log('Updated value:', updated);
      return updated; // Ensure updated object is returned
    });
  } else {
    setRules(prev => ({ ...(prev || {}), [key]: rawValue }));
  }
}, [isAdjustMode, setOriginalSplitRule, setRules]);

  // Strategy change handling
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
      <div className="flex flex-col gap-4" style={{ gridTemplateColumns: '114px 1fr' }}>
        <div className="space-y-4 p-4 border rounded-lg">
          <h3 className="font-bold text-gray-800 text-left text-md">{t('splitSettings')}</h3>

          <div className="flex gap-4">
            {/* Core modification: Adjust spacing based on showPreview */}
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
                <span className="absolute right-8 top-1/2 -translate-y-1/2 text-gray-400">{t('characters')}</span>
              </div>
            </div>

            {/* Core modification: Adjust spacing based on showPreview */}
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
                <span className="absolute right-8 top-1/2 -translate-y-1/2 text-gray-400">{t('characters')}</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 pt-2">
            <Checkbox
              id="retainImages"
              checked={internalValues.retainImages}
              onCheckedChange={(e) => handleSettingChange('retainImages', e)}
            />
            <Label htmlFor="retainImages" className="text-sm text-gray-700 flex items-center gap-1">
              {t('keepImages')}
              <Tooltip>
                <TooltipTrigger asChild>
                  <CircleHelp className="w-3.5 h-3.5 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent>
                  <div className="max-w-96 text-left break-all whitespace-normal">{t('retainImagesTooltip')}</div>
                </TooltipContent>
              </Tooltip>
            </Label>
          </div>
        </div>

        <div className="p-4 border rounded-lg">
          <Label htmlFor="splitMethod" className="flex justify-start text-md text-left font-bold text-gray-800">
            {t('splitMethod')}
          </Label>
          <FileUploadSplitStrategy data={strategies} onChange={handleStrategiesChange} />
        </div>

        {(appConfig.enableEtl4lm && rules.fileList.some(item => item.suffix === 'pdf') )&& (
          <div className="space-y-4 p-4 border rounded-lg">
            <h3 className="text-md font-bold text-gray-800 text-left ">{t('pdfAnalysis')}</h3>
            <div className="flex items-center gap-2 pt-2">
              <Checkbox
                id="forceOcr"
                checked={internalValues.forceOcr}
                onCheckedChange={(e) => handleSettingChange('forceOcr', e)}
              />
              <Label htmlFor="forceOcr" className="text-sm text-gray-700 flex items-center gap-1">
                {t('ocrForce')}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <CircleHelp className="w-3.5 h-3.5 text-muted-foreground" />
                  </TooltipTrigger>
                  <TooltipContent>
                    <div className="max-w-96 text-left break-all whitespace-normal">{t('ocrForceTip')}</div>
                  </TooltipContent>
                </Tooltip>
              </Label>
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