import { Checkbox } from "@/components/bs-ui/checkBox";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { useMemo, useEffect, useState, useRef, useCallback } from "react";
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

    const { t, i18n } = useTranslation('knowledge');
    const isZhLanguage = i18n.resolvedLanguage?.startsWith('zh');
    const appendTitleTooltipImageSrc = useMemo(
        () => isZhLanguage ? '/append-title-tooltip-zh.png' : '/append-title-tooltip-intl.png',
        [isZhLanguage]
    );
    const splitLevelTooltipImageSrc = useMemo(
        () => isZhLanguage ? '/split-level-tooltip-zh.png' : '/split-level-tooltip-intl.png',
        [isZhLanguage]
    );
    const mediumTitleStyle = useMemo(() => ({
        fontFamily: '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans SC", sans-serif',
        fontWeight: 500
    }), []);
    const renderTooltipWithImage = useCallback((imageSrc: string, imageAltKey: string, imageClassName = "w-[320px]") => (
        <div className="overflow-hidden rounded-[10px] border border-white/15 bg-white p-1">
            <img
                src={imageSrc}
                alt={t(imageAltKey)}
                className={`block max-w-full rounded-[8px] ${imageClassName}`}
            />
        </div>
    ), [t]);

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

    // const hasPdf = useMemo(() => rules?.fileList?.some(item => item.suffix === 'pdf'), [rules]);
    const hasPdf = false;

    const splitModes = [
        { id: 'auto', title: t('autoSplit'), desc: t('autoSplitDesc') },
        { id: 'custom', title: t('customSplit'), desc: t('customSplitDesc') },
        { id: 'hierarchical', title: t('hierarchicalSplit'), desc: t('hierarchicalSplitDesc') }
    ];

    return (
        <div className="relative flex flex-1 flex-col overflow-y-auto pb-6">
            <div className="flex flex-col gap-6">
                {/* Document Parsing Strategy */}
                <div className="space-y-4 text-left">
                    <h3 className="text-[16px] text-[#0f172a]" style={mediumTitleStyle}>
                        {t('docAnalysisStrategy')}
                    </h3>
                    <div className="flex flex-col gap-5 rounded-[10px] border border-[#e4e8ee] bg-white p-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
                        <div className="flex items-center gap-2">
                            <Checkbox
                                id="retainImages"
                                checked={internalValues.retainImages}
                                onCheckedChange={(e) => handleSettingChange('retainImages', e)}
                            />
                            <Label htmlFor="retainImages" className="text-sm text-gray-700 flex items-center gap-1 cursor-pointer">
                                {t('keepImages')}
                                <QuestionTooltip className="text-[#999999]" content={t('retainImagesTooltip')} />
                            </Label>
                        </div>

                        {hasPdf && (
                            <>
                                <p className="text-sm text-[#999999]">
                                    {t('pdfOptionsHint', { defaultValue: '检测到上传文件包含 PDF 文件，以下选项可用：' })}
                                </p>
                                <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
                                    <div className="flex items-center gap-2">
                                        <Checkbox
                                            id="forceOcr"
                                            checked={internalValues.forceOcr}
                                            onCheckedChange={(e) => handleSettingChange('forceOcr', e)}
                                        />
                                        <Label htmlFor="forceOcr" className="text-sm text-gray-700 flex items-center gap-1 cursor-pointer">
                                            {t('ocrForce')}
                                            <QuestionTooltip className="text-[#999999]" content={t('ocrForceTip')} />
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
                                            <QuestionTooltip className="text-[#999999]" content={t('hfFilterTooltip')} />
                                        </Label>
                                    </div>
                                </div>
                            </>
                        )}

                    </div>
                </div>

                {/* Document Slicing Strategy */}
                <div className="space-y-4 text-left">
                    <h3 className="text-[16px] text-[#0f172a]" style={mediumTitleStyle}>
                        {t('docSplitStrategy')}
                    </h3>

                    <div className="grid gap-4 lg:grid-cols-3">
                        {splitModes.map((mode) => (
                            <div
                                key={mode.id}
                                onClick={() => handleSettingChange('splitMode', mode.id)}
                                className={cn(
                                    "relative flex h-full min-h-[100px] cursor-pointer flex-col rounded-[10px] border p-4 transition-colors duration-200",
                                    internalValues.splitMode === mode.id
                                        ? "border-primary bg-primary/5"
                                        : "border-[#e4e8ee] bg-white hover:bg-[#f7f8fa]"
                                )}
                            >
                                <div className="mb-1 flex items-start justify-between">
                                    <span className="text-[14px] text-gray-800" style={mediumTitleStyle}>{mode.title}</span>
                                    {internalValues.splitMode === mode.id
                                        ? <CheckCircle2 className="size-5 shrink-0 text-primary" />
                                        : <Circle className="size-5 shrink-0 text-gray-200" />
                                    }
                                </div>
                                <p className="text-[14px] leading-relaxed text-gray-500 break-words">
                                    {mode.desc}
                                </p>
                            </div>
                        ))}
                    </div>

                    <div className="flex flex-col gap-5 rounded-[10px] border border-[#e4e8ee] bg-white p-4 sm:p-5">
                        {internalValues.splitMode === 'auto' && (
                            <div className="flex flex-wrap gap-8">
                                <div className="flex items-center gap-3">
                                    <Label className="whitespace-nowrap text-sm text-gray-600 min-w-[90px]">{t('splitLength')}</Label>
                                    <div className="flex h-9 overflow-hidden rounded-md border border-input bg-white">
                                        <Input
                                            type="number"
                                            step="100"
                                            min={0}
                                            value={internalValues.chunkSize}
                                            onChange={(e) => handleSettingChange('chunkSize', e)}
                                            boxClassName="w-[150px]"
                                            className="h-full rounded-none border-0 bg-transparent shadow-none focus-visible:ring-0"
                                            onBlur={(e) => {
                                                if (!e.target.value) handleSettingChange('chunkSize', { target: { value: '1000' } });
                                            }}
                                        />
                                        <div className="pointer-events-none flex items-center border-l border-[#ebecf0] bg-white px-3 text-sm text-[#9ca3af]">
                                            {t('characters')}
                                        </div>
                                    </div>
                                </div>
                                <div className="flex items-center gap-3">
                                    <Label className="whitespace-nowrap text-sm text-gray-600 min-w-[90px]">{t('chunkOverlap')}</Label>
                                    <div className="flex h-9 overflow-hidden rounded-md border border-input bg-white">
                                        <Input
                                            type="number"
                                            step="10"
                                            min={0}
                                            value={internalValues.chunkOverlap}
                                            onChange={(e) => handleSettingChange('chunkOverlap', e)}
                                            boxClassName="w-[150px]"
                                            className="h-full rounded-none border-0 bg-transparent shadow-none focus-visible:ring-0"
                                            onBlur={(e) => {
                                                if (!e.target.value) handleSettingChange('chunkOverlap', { target: { value: '0' } });
                                            }}
                                        />
                                        <div className="pointer-events-none flex items-center border-l border-[#ebecf0] bg-white px-3 text-sm text-[#9ca3af]">
                                            {t('characters')}
                                        </div>
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
                                        <div className="flex h-9 overflow-hidden rounded-md border border-input bg-white">
                                            <Input
                                                id="splitLength"
                                                type="number"
                                                step="100"
                                                min={0}
                                                value={internalValues.chunkSize}
                                                onChange={(e) => handleSettingChange('chunkSize', e)}
                                                placeholder={t('splitSizePlaceholder')}
                                                boxClassName="w-[150px]"
                                                className="h-full rounded-none border-0 bg-transparent shadow-none focus-visible:ring-0"
                                                onBlur={(e) => {
                                                    if (!e.target.value) handleSettingChange('chunkSize', { target: { value: '1000' } });
                                                }}
                                            />
                                            <div className="pointer-events-none flex items-center border-l border-[#ebecf0] bg-white px-3 text-sm text-[#9ca3af]">
                                                {t('characters')}
                                            </div>
                                        </div>
                                    </div>

                                    <div className="flex items-center gap-3">
                                        <Label htmlFor="chunkOverlap" className="whitespace-nowrap text-sm text-gray-600 min-w-[90px]">
                                            {t('chunkOverlap')}
                                        </Label>
                                        <div className="flex h-9 overflow-hidden rounded-md border border-input bg-white">
                                            <Input
                                                id="chunkOverlap"
                                                type="number"
                                                step="10"
                                                min={0}
                                                value={internalValues.chunkOverlap}
                                                onChange={(e) => handleSettingChange('chunkOverlap', e)}
                                                placeholder={t('chunkOverlapPlaceholder')}
                                                boxClassName="w-[150px]"
                                                className="h-full rounded-none border-0 bg-transparent shadow-none focus-visible:ring-0"
                                                onBlur={(e) => {
                                                    if (!e.target.value) handleSettingChange('chunkOverlap', { target: { value: '0' } });
                                                }}
                                            />
                                            <div className="pointer-events-none flex items-center border-l border-[#ebecf0] bg-white px-3 text-sm text-[#9ca3af]">
                                                {t('characters')}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <div className="pt-2">
                                    <FileUploadSplitStrategy data={strategies} onChange={handleStrategiesChange} />
                                </div>
                            </div>
                        )}

                        {internalValues.splitMode === 'hierarchical' && (
                            <div className="flex flex-col gap-4">
                                <div className="flex flex-wrap items-center gap-x-12 gap-y-4">
                                    <div className="flex items-center gap-3">
                                        <Label htmlFor="hierarchyLevel" className="whitespace-nowrap text-sm text-gray-600">
                                            {t('splitLevel')}
                                        </Label>
                                        <div className="flex items-center gap-2">
                                            <div className="flex h-9 overflow-hidden rounded-md border border-input bg-white">
                                                <Input
                                                    id="hierarchyLevel"
                                                    type="number"
                                                    min={1}
                                                    max={5}
                                                    value={internalValues.hierarchyLevel}
                                                    onChange={(e) => handleSettingChange('hierarchyLevel', e)}
                                                    boxClassName="w-[120px]"
                                                    className="h-full rounded-none border-0 bg-transparent shadow-none focus-visible:ring-0"
                                                />
                                                <div className="pointer-events-none flex items-center border-l border-[#ebecf0] bg-white px-3 text-sm text-[#9ca3af]">
                                                    {t('layer')}
                                                </div>
                                            </div>
                                            <QuestionTooltip
                                                className="text-[#999]"
                                                content={renderTooltipWithImage(
                                                    splitLevelTooltipImageSrc,
                                                    'splitLevelTooltipImageAlt',
                                                    'w-[480px]'
                                                )}
                                            />
                                        </div>
                                    </div>

                                    <div className="flex items-center gap-3">
                                        <Label htmlFor="maxChunkSize" className="whitespace-nowrap text-sm text-gray-600">
                                            {t('maxChunkSize')}
                                        </Label>
                                        <div className="flex items-center gap-2">
                                            <div className="flex h-9 overflow-hidden rounded-md border border-input bg-white">
                                                <Input
                                                    id="maxChunkSize"
                                                    type="number"
                                                    step="100"
                                                    min={0}
                                                    value={internalValues.maxChunkSize}
                                                    onChange={(e) => handleSettingChange('maxChunkSize', e)}
                                                    boxClassName="w-[150px]"
                                                    className="h-full rounded-none border-0 bg-transparent shadow-none focus-visible:ring-0"
                                                />
                                                <div className="pointer-events-none flex items-center border-l border-[#ebecf0] bg-white px-3 text-sm text-[#9ca3af]">
                                                    {t('characters')}
                                                </div>
                                            </div>
                                        </div>
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
                                        <QuestionTooltip
                                            className="text-[#999]"
                                            content={renderTooltipWithImage(appendTitleTooltipImageSrc, 'appendTitleTooltipImageAlt')}
                                        />
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
