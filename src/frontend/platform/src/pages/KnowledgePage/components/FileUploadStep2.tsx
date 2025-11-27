"use client"
import { LoadingIcon } from "@/components/bs-icons/loading";
import { Button } from "@/components/bs-ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { cn } from "@/util/utils";
import { SearchCheck } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import useKnowledgeStore from "../useKnowledgeStore";
import PreviewResult from "./PreviewResult";
import RuleFile from "./RuleFile";
import RuleTable from "./RuleTable";

// 原有类型定义不变
export interface FileItem {
    split_rule: any;
    id: string;
    fileName: string;
    file_path: string;
    fileType: 'table' | 'file';
    suffix: string;
    isEtl4lm?: string;
}

// 新增：仅定义必要的持久化状态类型
export interface Step2PersistState {
    rules: any;
    applyEachCell: boolean;
    cellGeneralConfig: any;
    strategies: any[];
}

// 接口仅新增2个必要props，不改动原有参数
interface IProps {
    step: number;
    resultFiles: FileItem[];
    isSubmitting: boolean;
    onNext: (step: number, config?: any) => void;
    onPrev: () => void;
    isAdjustMode?: boolean;
    kId?: string | number;
    // 新增1：接收父组件保存的状态
    persistState?: Step2PersistState;
    // 新增2：状态变化时通知父组件
    onPersistStateChange?: (state: Step2PersistState) => void;
}

const enum DisplayModeType {
    OnlyTables = 'table',
    OnlyDocuments = 'file',
    Mixed = 'mixed'
}

const initialStrategies = [
    { id: '1', regex: '\\n\\n', position: 'after', rule: '双换行后切分,用于分隔段落' },
    { id: '2', regex: '\\n', position: 'after', rule: '单换行后切分，用于分隔普通换行' }
];

const FileUploadStep2 = forwardRef(({
    step, resultFiles, isSubmitting, onNext, onPrev, isAdjustMode, kId,
    persistState, 
    onPersistStateChange
}: IProps, ref) => {
    const [previewLoading, setPreviewLoading] = useState(false);
    const [previewFailed, setPreviewFailed] = useState(false);
    const [showPreview, setShowPreview] = useState(false);
    const [previewCount, setPreviewCount] = useState(0);
    const [applyRule, setApplyRule] = useState<any>({});
    const applyRuleRef = useRef(applyRule);
    const { id: kid } = useParams();
    const { t } = useTranslation('knowledge');
    const setSelectedChunkIndex = useKnowledgeStore((state) => state.setSelectedChunkIndex);
    const splitRule = resultFiles[0]?.split_rule;
    const isEtl4lm = resultFiles[0]?.isEtl4lm === 'etl4lm';
    const displayStep = isAdjustMode ? step + 1 : step;

    const displayMode: DisplayModeType | null = useMemo(() => {
        if (!resultFiles || resultFiles.length === 0) return null;
        const hasTableFiles = resultFiles.some(file => file.fileType === 'table');
        const hasDocumentFiles = resultFiles.some(file => file.fileType === 'file');
        return hasTableFiles && !hasDocumentFiles ? DisplayModeType.OnlyTables :
            !hasTableFiles && hasDocumentFiles ? DisplayModeType.OnlyDocuments :
                DisplayModeType.Mixed;
    }, [resultFiles]);

    // 核心修改1：初始化规则时，优先使用父组件传递的persistState
    const {
        rules,
        setRules,
        applyEachCell,
        setApplyEachCell,
        cellGeneralConfig,
        setCellGeneralConfig,
        strategies,
        setStrategies
    } = useFileProcessingRules(
        persistState?.strategies || initialStrategies,
        resultFiles,
        kid || kId,
        splitRule,
        persistState?.rules,
        persistState?.applyEachCell ?? false,
        persistState?.cellGeneralConfig
    );

    // 核心修改2：状态变化时，通知父组件更新（仅新增这一段）
    useEffect(() => {
        if (onPersistStateChange) {
            onPersistStateChange({
                rules,
                applyEachCell,
                cellGeneralConfig,
                strategies
            });
        }
    }, [rules, applyEachCell, cellGeneralConfig, strategies, onPersistStateChange]);

    // 原有逻辑完全不变
    useEffect(() => {
        applyRuleRef.current = applyRule;
    }, [applyRule]);

    useEffect(() => {
        setApplyRule({
            applyEachCell,
            cellGeneralConfig,
            rules
        });
    }, [applyEachCell, cellGeneralConfig, rules]);

    const vildateCell = () => {
        if (applyEachCell
            ? rules.fileList.some(file => file.excelRule.append_header && Number(file.excelRule.header_start_row) > Number(file.excelRule.header_end_row))
            : cellGeneralConfig.append_header && Number(cellGeneralConfig.header_start_row) > Number(cellGeneralConfig.header_end_row)) {
            toast({ variant: 'warning', description: t('minRowGreaterThanMaxRow') });
            return true;
        }

        const chunkSizeNum = Number((rules as any)?.chunkSize ?? (rules as any)?.chunk_size ?? 0);
        const chunkOverlapNum = Number((rules as any)?.chunkOverlap ?? (rules as any)?.chunk_overlap ?? 0);
        if (!Number.isNaN(chunkSizeNum) && !Number.isNaN(chunkOverlapNum) && chunkOverlapNum > chunkSizeNum) {
            toast({ variant: 'warning', description: t('overlapGreaterThanChunkSize') });
            return true;
        }

        return false;
    };

    const { toast } = useToast();

    const internalHandleNext = () => {
        if (vildateCell()) return;
        const hasEmptyCustomRule = (strategies || []).some(s => String(s?.regex ?? '') === '');
        if (hasEmptyCustomRule) {
            toast({ variant: 'warning', description: t('customRuleNotEmpty') });
            return;
        }
        if (!rules.separator || rules.separator.length === 0) {
            toast({ variant: 'warning', description: t('addAtLeastOneSplitRule') });
            return;
        }

        const nextStep = step + 1;
        if (step === 2 || displayStep === 2) {
            const config = { applyEachCell, cellGeneralConfig, rules };
            setApplyRule(config);
            setSelectedChunkIndex(-1);
            return onNext(nextStep, config);
        }

        const { fileList, pageHeaderFooter, chunkOverlap, chunkSize, enableFormula, forceOcr, retainImages, separator, separatorRule } = rules;
        const params = {
            knowledge_id: kid || kId,
            file_list: fileList.map(item => ({
                file_path: item.filePath,
                excel_rule: applyEachCell ? item.excelRule : cellGeneralConfig
            })),
            separator,
            separator_rule: separatorRule,
            chunk_size: chunkSize,
            chunk_overlap: chunkOverlap,
            retain_images: retainImages,
            enable_formula: enableFormula,
            force_ocr: forceOcr,
            fileter_page_header_footer: pageHeaderFooter
        };

        onNext(nextStep, params);
    };

    useImperativeHandle(ref, () => ({
        handleNext: internalHandleNext
    }));

    const handlePreview = () => {
        if (vildateCell()) return;
        const hasEmptyCustomRule = (strategies || []).some(s => String(s?.regex ?? '') === '');
        if (hasEmptyCustomRule) {
            toast({ variant: 'warning', description: t('customRuleNotEmpty') });
            return;
        }
        if (!rules.separator || rules.separator.length === 0) {
            toast({ variant: 'warning', description: t('addAtLeastOneSplitRule') });
            return;
        }

        setShowPreview(true);
        setPreviewLoading(true);
        setPreviewCount(c => c + 1);
        setApplyRule({
            applyEachCell,
            cellGeneralConfig,
            rules: { ...rules, knowledgeId: kId }
        });
    };
    return (
        <div className="w-full">
            <div className={cn("flex flex-row justify-center gap-4", showPreview ? "px-4" : "")}>
                {displayStep === 2 && (
                    <div className={cn(
                        "h-full flex flex-col min-w-[540px]",
                        showPreview ? "max-w-1/2" : ""
                    )}>
                        <Tabs
                            defaultValue={displayMode === DisplayModeType.Mixed ? 'file' : displayMode}
                            className="flex flex-col h-full"
                        >
                            <div className="">
                                {displayMode === DisplayModeType.Mixed ? (
                                    <TabsList className="">
                                        <TabsTrigger id="knowledge_file_tab" value="file" className="roundedrounded-xl">{t('defStrategy')}</TabsTrigger>
                                        <TabsTrigger id="knowledge_table_tab" value="table">{t('cusStrategy')}</TabsTrigger>
                                    </TabsList>
                                ) : <div className="h-1"></div>}
                            </div>
                            <TabsContent value="file">
                                <RuleFile
                                    rules={rules}
                                    setRules={setRules}
                                    strategies={strategies}
                                    setStrategies={(next) => setStrategies(next)}
                                    isEtl4lm={isEtl4lm}
                                    showPreview={showPreview}
                                />
                            </TabsContent>
                            <TabsContent value="table">
                                <RuleTable
                                    rules={rules}
                                    setRules={setRules}
                                    applyEachCell={applyEachCell}
                                    setApplyEachCell={setApplyEachCell}
                                    cellGeneralConfig={cellGeneralConfig}
                                    setCellGeneralConfig={setCellGeneralConfig}
                                    showPreview={showPreview}
                                />
                            </TabsContent>
                            <div className="mt-4">
                                <Button
                                    className="h-8"
                                    onClick={handlePreview}
                                    disabled={strategies.length === 0}
                                >
                                    <SearchCheck size={16} />
                                    {showPreview ? t('repreviewSegmentation') : t('previewResults')}
                                </Button>
                            </div>
                        </Tabs>
                    </div>
                )}

                {(showPreview || (step === 3 && !isAdjustMode)) ? (
                    <div className={cn(
                        "relative",
                        showPreview ? "w-1/2" : ""
                    )}>
                        <PreviewResult
                            showPreview={showPreview}
                            step={step}
                            previewCount={previewCount}
                            kId={kId}
                            rules={applyRule.rules}
                            applyEachCell={applyRule.applyEachCell}
                            cellGeneralConfig={applyRule.cellGeneralConfig}
                            handlePreviewResult={(isSuccess) => {
                                setPreviewFailed(!isSuccess);
                                setPreviewLoading(false);
                            }}
                        />
                    </div>
                ) : null}
            </div >

            <div className="fixed bottom-2 right-12 flex gap-4 bg-white p-2 rounded-lg shadow-sm z-10">
                <Button
                    className="h-8"
                    variant="outline"
                    onClick={() => {
                        onPrev()
                        step === 2 && setShowPreview(false)
                    }}
                >
                    {t('previousStep')}
                </Button>
                <Button
                    className="h-8"
                    disabled={previewFailed || isSubmitting || strategies.length === 0}
                    onClick={internalHandleNext}
                >
                    {isSubmitting ? (
                        <LoadingIcon className="h-12 w-12" />
                    ) : (
                        t('nextStep')
                    )}
                </Button>
            </div>
        </div>
    );
});

FileUploadStep2.displayName = 'FileUploadStep2';

export default FileUploadStep2;

const useFileProcessingRules = (
    initialStrategies,
    resultFiles,
    kid,
    splitRule,
    parentRules,
    parentApplyEachCell,
    parentCellGeneralConfig
) => {
    const { t } = useTranslation('knowledge');
    const parsedSplitRule = useMemo(() => {
        if (!splitRule) return {} as any;
        if (typeof splitRule === 'string') {
            try {
                const obj = JSON.parse(splitRule);
                return obj && typeof obj === 'object' ? obj : {};
            } catch (e) {
                console.error('splitRule 解析失败:', e);
                return {} as any;
            }
        }
        return splitRule || {};
    }, [splitRule]);

    const [rules, setRules] = useState(() => {
        if (parentRules) return { ...parentRules, knowledgeId: kid };
        return {
            knowledgeId: kid,
            fileList: [],
            separator: (parsedSplitRule?.separator || ['\\n\\n', '\\n']).map((s) =>
                typeof s === 'string' ? s.replace(/\n/g, '\\n') : s
            ),
            separatorRule: parsedSplitRule?.separator_rule || ['after', 'after'],
            chunkSize: parsedSplitRule?.chunk_size?.toString() || "1000",
            chunkOverlap: parsedSplitRule?.chunk_overlap?.toString() || "0",
            retainImages: parsedSplitRule?.retain_images ?? true,
            enableFormula: parsedSplitRule?.enable_formula ?? true,
            forceOcr: parsedSplitRule?.force_ocr ?? true,
            pageHeaderFooter: parsedSplitRule?.filter_page_header_footer ?? true
        };
    });

    const [applyEachCell, setApplyEachCell] = useState(() => {
        if (parentApplyEachCell !== undefined) return parentApplyEachCell;
        return parsedSplitRule?.excel_rule?.applyEachCell ?? false;
    });

    const [cellGeneralConfig, setCellGeneralConfig] = useState(() => {
        if (parentCellGeneralConfig) return parentCellGeneralConfig;
        return {
            slice_length: splitRule?.excel_rule?.slice_length || 10,
            append_header: splitRule?.excel_rule?.append_header || true,
            header_start_row: splitRule?.excel_rule?.header_start_row || 1,
            header_end_row: splitRule?.excel_rule?.header_end_row || 1
        };
    });

    const getStrategyRuleDescription = (regex) => {
        const ruleMap = {
            '\\n\\n': t('doubleNewlineRule'),
            '\\n': t('singleNewlineRule'),
            '\n\n': t('doubleNewlineRule'),
            '\n': t('singleNewlineRule'),
            '第.{1,3}章': t('chapterRule'),
            '第.{1,3}条': t('articleRule'),
            '。': t('chinesePeriodRule'),
            '\\.': t('englishPeriodRule')
        };
        return ruleMap[regex] || t('customRule', { regex });
    };

    const [strategies, setStrategies] = useState(() => {
        if (parentRules?.strategies) return parentRules.strategies;
        if (parsedSplitRule?.separator && parsedSplitRule?.separator_rule) {
            return parsedSplitRule.separator.map((regex, index) => ({
                id: `strategy-${index}`,
                regex: typeof regex === 'string' ? regex.replace(/\n/g, '\\n') : regex,
                position: parsedSplitRule.separator_rule[index] || 'after',
                rule: getStrategyRuleDescription(regex)
            }));
        }
        return initialStrategies;
    });
    // Update rules when strategies change（不过滤只含换行的规则）
    useEffect(() => {
        const cleaned = (strategies || []).filter(s => String(s?.regex ?? '') !== '');
        const [separator, separatorRule] = cleaned.reduce(([_separator, _separatorRule], strategy) => {
            const regex = String(strategy.regex).replace(/\n/g, '\\n');
            const position = strategy.position || 'after';
            return [[..._separator, regex], [..._separatorRule, position]];
        }, [[], []]);

        setRules(prev => ({
            ...prev,
            separator,
            separatorRule
        }));
    }, [strategies]);

    // Initialize rules when resultFiles change
    useEffect(() => {
        if (resultFiles && resultFiles.length > 0) {
            setRules(prev => ({
                ...prev,
                fileList: resultFiles.map(file => ({
                    id: file.id,
                    filePath: file.file_path,
                    fileName: file.fileName,
                    previewUrl: file.previewUrl,
                    suffix: file.suffix,
                    fileType: file.fileType,
                    excelRule: file.fileType === 'table' ? {
                        ...cellGeneralConfig
                    } : {}
                }))
            }));
        }
    }, [resultFiles, kid, cellGeneralConfig]);

    return {
        rules,
        setRules,
        applyEachCell,
        setApplyEachCell,
        cellGeneralConfig,
        setCellGeneralConfig,
        strategies,
        setStrategies
    };
};
