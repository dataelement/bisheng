import { Checkbox } from "@/components/bs-ui/checkBox";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { locationContext } from "@/contexts/locationContext";
import { useContext, useMemo, useEffect, useState, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import FileUploadSplitStrategy from "./FileUploadSplitStrategy";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { cn } from "@/utils";
import { CheckCircle2, Circle } from "lucide-react";

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
    setStrategies = () => { },
    originalSplitRule,
    setOriginalSplitRule = () => { },
    isAdjustMode = false,
    showPreview = false,
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
            splitMode: baseRules.split_mode ?? baseRules.splitMode ?? "auto",
            chunkSize: String(baseRules.chunk_size ?? baseRules.chunkSize ?? "1000"),
            chunkOverlap: String(baseRules.chunk_overlap ?? baseRules.chunkOverlap ?? "0"),
            retainImages: toBoolean(baseRules.retain_images ?? baseRules.retainImages),
            forceOcr: toBoolean(baseRules.force_ocr ?? baseRules.forceOcr),
            enableFormula: toBoolean(baseRules.enable_formula ?? baseRules.enableFormula),
            pageHeaderFooter: toBoolean(baseRules.filter_page_header_footer ?? baseRules.pageHeaderFooter ?? false),
            hierarchyLevel: String(baseRules.hierarchy_level ?? baseRules.hierarchyLevel ?? "3"),
            appendTitle: toBoolean(baseRules.append_title ?? baseRules.appendTitle ?? false),
            maxChunkSize: String(baseRules.max_chunk_size ?? baseRules.maxChunkSize ?? "1000"),
        };
    }, [isAdjustMode, parsedOriginalSplitRule, rules]);

    const [internalValues, setInternalValues] = useState(currentRules);
    const prevRulesRef = useRef(currentRules);

    useEffect(() => {
        if (JSON.stringify(prevRulesRef.current) !== JSON.stringify(currentRules)) {
            setInternalValues(currentRules);
            prevRulesRef.current = currentRules;
        }
    }, [currentRules]);

    const handleSettingChange = useCallback((key, value) => {
        let rawValue;
        if (value?.target?.type === 'checkbox') {
            rawValue = value.target.checked;
        } else if (value?.target?.value !== undefined) {
            rawValue = value.target.value;
        } else {
            rawValue = value;
        }

        setInternalValues(prev => ({ ...prev, [key]: rawValue }));

        if (isAdjustMode) {
            const snakeKey = camelToSnake(key);
            let storedValue;
            if (typeof rawValue === 'boolean') {
                storedValue = rawValue;
            } else if (key === 'chunkSize' || key === 'chunkOverlap' || key === 'hierarchyLevel' || key === 'maxChunkSize') {
                storedValue = rawValue === '' ? (key === 'chunkSize' ? 1000 : (key === 'hierarchyLevel' ? 3 : 0)) : Number(rawValue);
            } else {
                storedValue = rawValue;
            }

            setOriginalSplitRule(prev => {
                const current = typeof prev === 'string' ? (() => { try { return JSON.parse(prev); } catch { return {}; } })() : (prev || {});
                return { ...current, [snakeKey]: storedValue };
            });
        } else {
            setRules(prev => ({ ...(prev || {}), [key]: rawValue }));
        }
    }, [isAdjustMode, setOriginalSplitRule, setRules]);

    const handleStrategiesChange = useCallback((newStrategies) => {
        setStrategies(newStrategies);
        if (isAdjustMode) {
            const separator = newStrategies.map(s => s.regex);
            const separatorRule = newStrategies.map(s => s.position);
            setOriginalSplitRule(prev => {
                const current = typeof prev === 'string' ? (() => { try { return JSON.parse(prev); } catch { return {}; } })() : (prev || {});
                return { ...current, separator, separator_rule: separatorRule };
            });
        }
    }, [isAdjustMode, setOriginalSplitRule, setStrategies]);

    const hasPdf = useMemo(() => rules?.fileList?.some(item => item.suffix === 'pdf'), [rules]);

    const splitModes = [
        { id: 'auto', title: t('autoSplit'), desc: t('autoSplitDesc') },
        { id: 'custom', title: t('customSplit'), desc: t('customSplitDesc') },
        { id: 'hierarchical', title: t('hierarchicalSplit'), desc: t('hierarchicalSplitDesc') }
    ];

    return (
        <div className="flex-1 flex flex-col relative max-w-[960px] mx-auto overflow-y-auto pb-10">
            <div className="flex flex-col gap-6">
                {/* Document Parsing Strategy */}
                <div className="space-y-3 text-left">
                    <h3 className="font-bold text-gray-800 text-[14px]">
                        {t('docAnalysisStrategy')}
                    </h3>
                    <div className="flex flex-wrap items-center gap-6 p-4 border rounded-lg bg-white shadow-sm">
                        <div className="flex items-center gap-2">
                            <Checkbox
                                id="retainImages"
                                checked={internalValues.retainImages}
                                onCheckedChange={(e) => handleSettingChange('retainImages', e)}
                            />
                            <Label htmlFor="retainImages" className="text-sm text-gray-700 flex items-center gap-1 cursor-pointer">
                                {t('keepImages')}
                                <QuestionTooltip content={t('retainImagesTooltip')} />
                            </Label>
                        </div>

                        {hasPdf && (
                            <>
                                <div className="flex items-center gap-2">
                                    <Checkbox
                                        id="forceOcr"
                                        checked={internalValues.forceOcr}
                                        onCheckedChange={(e) => handleSettingChange('forceOcr', e)}
                                    />
                                    <Label htmlFor="forceOcr" className="text-sm text-gray-700 flex items-center gap-1 cursor-pointer">
                                        {t('ocrForce')}
                                        <QuestionTooltip content={t('ocrForceTip')} />
                                    </Label>
                                </div>
                                <div className="flex items-center gap-2">
                                    <Checkbox
                                        id="enableFormula"
                                        checked={internalValues.enableFormula}
                                        onCheckedChange={(e) => handleSettingChange('enableFormula', e)}
                                    />
                                    <Label htmlFor="enableFormula" className="text-sm text-gray-700 cursor-pointer">{t('enableRec')}</Label>
                                </div>
                                <div className="flex items-center gap-2">
                                    <Checkbox
                                        id="pageHeaderFooter"
                                        checked={internalValues.pageHeaderFooter}
                                        onCheckedChange={(e) => handleSettingChange('pageHeaderFooter', e)}
                                    />
                                    <Label htmlFor="pageHeaderFooter" className="text-sm text-gray-700 flex items-center gap-1 cursor-pointer">
                                        {t('hfFilter')}
                                        <QuestionTooltip content={t('hfFilterTooltip')} />
                                    </Label>
                                </div>
                            </>
                        )}
                    </div>
                </div>

                {/* Document Slicing Strategy */}
                <div className="space-y-3 text-left">
                    <h3 className="font-bold text-gray-800 text-[14px]">
                        {t('docSplitStrategy')}
                    </h3>

                    <div className="grid grid-cols-3 gap-4">
                        {splitModes.map((mode) => (
                            <div
                                key={mode.id}
                                onClick={() => handleSettingChange('splitMode', mode.id)}
                                className={cn(
                                    "relative p-4 border rounded-lg cursor-pointer transition-all duration-200 bg-white hover:shadow-md h-[100px]",
                                    internalValues.splitMode === mode.id
                                        ? "border-primary bg-primary/5 shadow-sm"
                                        : "border-gray-200"
                                )}
                            >
                                <div className="flex justify-between items-start mb-1">
                                    <span className="font-bold text-[14px] text-gray-800">{mode.title}</span>
                                    {internalValues.splitMode === mode.id
                                        ? <CheckCircle2 className="size-5 text-primary" />
                                        : <Circle className="size-5 text-gray-200" />
                                    }
                                </div>
                                <p className="text-xs text-gray-500 leading-relaxed line-clamp-3">
                                    {mode.desc}
                                </p>
                            </div>
                        ))}
                    </div>

                    <div className="mt-4 p-6 bg-gray-50/80 rounded-lg border border-gray-100 flex flex-col gap-4">
                        {internalValues.splitMode === 'auto' && (
                            <div className="flex flex-wrap gap-8">
                                <div className="flex items-center gap-3">
                                    <Label className="whitespace-nowrap text-sm text-gray-600 min-w-[90px]">{t('splitLength')}</Label>
                                    <div className="relative group">
                                        <Input
                                            type="number"
                                            step="100"
                                            min={0}
                                            value={internalValues.chunkSize}
                                            onChange={(e) => handleSettingChange('chunkSize', e)}
                                            className="w-[150px] bg-white border-gray-200 h-9"
                                            onBlur={(e) => {
                                                if (!e.target.value) handleSettingChange('chunkSize', { target: { value: '1000' } });
                                            }}
                                        />
                                        <span className="absolute right-8 top-1/2 -translate-y-1/2 text-xs text-gray-400 pointer-events-none">{t('characters')}</span>
                                    </div>
                                </div>
                                <div className="flex items-center gap-3">
                                    <Label className="whitespace-nowrap text-sm text-gray-600 min-w-[90px]">{t('chunkOverlap')}</Label>
                                    <div className="relative">
                                        <Input
                                            type="number"
                                            step="10"
                                            min={0}
                                            value={internalValues.chunkOverlap}
                                            onChange={(e) => handleSettingChange('chunkOverlap', e)}
                                            className="w-[150px] bg-white border-gray-200 h-9"
                                            onBlur={(e) => {
                                                if (!e.target.value) handleSettingChange('chunkOverlap', { target: { value: '0' } });
                                            }}
                                        />
                                        <span className="absolute right-8 top-1/2 -translate-y-1/2 text-xs text-gray-400 pointer-events-none">{t('characters')}</span>
                                    </div>
                                </div>
                            </div>
                        )}

                        {internalValues.splitMode === 'custom' && (
                            <div className="space-y-6">
                                <div className="flex flex-wrap gap-8">
                                    <div className="flex items-center gap-3">
                                        <Label htmlFor="splitLength" className="whitespace-nowrap text-sm text-gray-600 min-w-[90px]">
                                            {t('splitLength')}
                                        </Label>
                                        <div className="relative">
                                            <Input
                                                id="splitLength"
                                                type="number"
                                                step="100"
                                                min={0}
                                                value={internalValues.chunkSize}
                                                onChange={(e) => handleSettingChange('chunkSize', e)}
                                                placeholder={t('splitSizePlaceholder')}
                                                className="w-[150px] bg-white h-9"
                                                onBlur={(e) => {
                                                    if (!e.target.value) handleSettingChange('chunkSize', { target: { value: '1000' } });
                                                }}
                                            />
                                            <span className="absolute right-8 top-1/2 -translate-y-1/2 text-xs text-gray-400 pointer-events-none">{t('characters')}</span>
                                        </div>
                                    </div>

                                    <div className="flex items-center gap-3">
                                        <Label htmlFor="chunkOverlap" className="whitespace-nowrap text-sm text-gray-600 min-w-[90px]">
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
                                                className="w-[150px] bg-white h-9"
                                                onBlur={(e) => {
                                                    if (!e.target.value) handleSettingChange('chunkOverlap', { target: { value: '0' } });
                                                }}
                                            />
                                            <span className="absolute right-8 top-1/2 -translate-y-1/2 text-xs text-gray-400 pointer-events-none">{t('characters')}</span>
                                        </div>
                                    </div>
                                </div>
                                <div className="pt-2">
                                    <FileUploadSplitStrategy data={strategies} onChange={handleStrategiesChange} />
                                </div>
                            </div>
                        )}

                        {internalValues.splitMode === 'hierarchical' && (
                            <div className="flex flex-wrap items-center gap-x-12 gap-y-4">
                                <div className="flex items-center gap-3">
                                    <Label htmlFor="maxChunkSize" className="whitespace-nowrap text-sm text-gray-600">
                                        {t('maxChunkSize')}
                                    </Label>
                                    <div className="flex items-center gap-2">
                                        <div className="relative">
                                            <Input
                                                id="maxChunkSize"
                                                type="number"
                                                step="100"
                                                min={0}
                                                value={internalValues.maxChunkSize}
                                                onChange={(e) => handleSettingChange('maxChunkSize', e)}
                                                className="w-[150px] bg-white h-9"
                                            />
                                            <span className="absolute right-8 top-1/2 -translate-y-1/2 text-xs text-gray-400 pointer-events-none">{t('characters')}</span>
                                        </div>
                                        <QuestionTooltip content={t('maxChunkSizeTooltip')} />
                                    </div>
                                </div>

                                <div className="flex items-center gap-3">
                                    <Label htmlFor="hierarchyLevel" className="whitespace-nowrap text-sm text-gray-600">
                                        {t('splitLevel')}
                                    </Label>
                                    <div className="flex items-center gap-2">
                                        <div className="relative">
                                            <Input
                                                id="hierarchyLevel"
                                                type="number"
                                                min={1}
                                                max={5}
                                                value={internalValues.hierarchyLevel}
                                                onChange={(e) => handleSettingChange('hierarchyLevel', e)}
                                                className="w-[100px] bg-white h-9"
                                            />
                                            <span className="absolute right-8 top-1/2 -translate-y-1/2 text-sm text-gray-500 pointer-events-none">{t('layer')}</span>
                                        </div>
                                        <QuestionTooltip content={t('splitLevelTooltip')} />
                                    </div>
                                </div>

                                <div className="flex items-center gap-2">
                                    <Checkbox
                                        id="appendTitle"
                                        checked={internalValues.appendTitle}
                                        onCheckedChange={(e) => handleSettingChange('appendTitle', e)}
                                    />
                                    <Label htmlFor="appendTitle" className="text-sm text-gray-700 flex items-center gap-1 cursor-pointer">
                                        {t('appendTitle')}
                                        <QuestionTooltip content={t('appendTitleTooltip')} />
                                    </Label>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}