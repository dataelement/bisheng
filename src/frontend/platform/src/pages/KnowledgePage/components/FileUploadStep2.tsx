import { Button } from "@/components/bs-ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { cn } from "@/util/utils";
import { SearchCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import PreviewResult from "./PreviewResult";
import RuleFile from "./RuleFile";
import RuleTable from "./RuleTable";

export interface FileItem {
    id: string;
    fileName: string;
    file_path: string;
    fileType: 'table' | 'file';
    suffix: string;
}
interface IProps {
    step: number
    resultFiles: FileItem[]
    onNext: (step: number, config?: any) => void
    onPrev: () => void
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

export default function FileUploadStep2({ step, resultFiles, onNext, onPrev }: IProps) {
    const { id: kid } = useParams()
    const { t } = useTranslation('knowledge')

    const displayMode: DisplayModeType = useMemo(
        () => {
            const hasTableFiles = resultFiles.some(file => file.fileType === 'table');
            const hasDocumentFiles = resultFiles.some(file => file.fileType === 'file');
            return hasTableFiles && !hasDocumentFiles ? DisplayModeType.OnlyTables :
                !hasTableFiles && hasDocumentFiles ? DisplayModeType.OnlyDocuments :
                    DisplayModeType.Mixed;
        }, [resultFiles]
    )

    const [showPreview, setShowPreview] = useState(false)
    const [previewCount, setPreviewCount] = useState(0) // 预览次数
    const {
        rules,
        setRules,
        applyEachCell,
        setApplyEachCell,
        cellGeneralConfig,
        setCellGeneralConfig,
        strategies,
        setStrategies
    } = useFileProcessingRules(initialStrategies, resultFiles, kid);

    const handleNext = () => {
        const nextStep = step + 1
        if (step === 2) {
            return onNext(nextStep);
        }
        //  合并配置
        const { fileList, pageHeaderFooter, chunkOverlap, chunkSize, enableFormula, forceOcr
            , retainImages, separator, separatorRule } = rules;

        const params = {
            knowledge_id: kid,
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
        }
        onNext(nextStep, params);
    };

    if (![2, 3].includes(step)) return null

    return <div>
        <div className="flex flex-row justify-center gap-4">
            {/* 左侧区域 */}
            {
                step === 2 && <div className={cn(" h-full flex flex-col max-w-[760px]", showPreview ? 'w-1/2' : 'w-2/3')}>
                    <Tabs
                        defaultValue={displayMode === DisplayModeType.Mixed ? 'file' : displayMode}
                        className="flex flex-col h-full"
                    >
                        {/* 标签页头部 */}
                        <div className="">
                            {displayMode === DisplayModeType.Mixed ? (
                                <TabsList className="">
                                    <TabsTrigger value="file" className="roundedrounded-xl">{t('defaultStrategy')}</TabsTrigger>
                                    <TabsTrigger value="table">{t('customStrategy')}</TabsTrigger>
                                </TabsList>
                            ) : <div className="h-10"></div>}
                        </div>
                        {/* 文件文档设置 */}
                        <TabsContent value="file">
                            <RuleFile
                                rules={rules}
                                setRules={setRules}
                                strategies={strategies}
                                setStrategies={setStrategies}
                            />
                        </TabsContent>
                        {/* 表格文档设置 */}
                        <TabsContent value="table">
                            <RuleTable
                                rules={rules}
                                setRules={setRules}
                                applyEachCell={applyEachCell}
                                setApplyEachCell={setApplyEachCell}
                                cellGeneralConfig={cellGeneralConfig}
                                setCellGeneralConfig={setCellGeneralConfig}
                            />
                        </TabsContent>
                        {/* 预览分段按钮 */}
                        <div className="mt-4">
                            <Button
                                className="h-8"
                                onClick={() => {
                                    setShowPreview(true)
                                    setPreviewCount(c => c + 1) // 刷新分段
                                }}
                                disabled={strategies.length === 0}
                            >
                                <SearchCheck size={16} />
                                {showPreview ? '重新预览分段' : t('previewResults')}
                            </Button>
                        </div>
                    </Tabs>
                </div>
            }
            {/* 原文预览 & 分段预览 */}
            {
                (showPreview || step === 3) && (
                    <PreviewResult
                        step={step}
                        previewCount={previewCount}
                        rules={rules}
                        applyEachCell={applyEachCell}
                        cellGeneralConfig={cellGeneralConfig}
                    />
                )
            }
        </div >
        <div className="fixed bottom-2 right-8 flex gap-4 bg-white p-2 rounded-lg shadow-sm">
            <Button
                className="h-8"
                variant="outline"
                onClick={() => {
                    onPrev()
                    step === 2 && setShowPreview(false) // step时关闭
                }}
            >
                {t('previousStep')}
            </Button>
            <Button
                className="h-8"
                disabled={strategies.length === 0}
                onClick={() => handleNext()}
            >
                {t('nextStep')}
            </Button>
        </div>
    </div>
};



const useFileProcessingRules = (initialStrategies, resultFiles, kid) => {
    const [rules, setRules] = useState(null);
    const [applyEachCell, setApplyEachCell] = useState(false); // 为每个表格单独设置
    const [cellGeneralConfig, setCellGeneralConfig] = useState({
        slice_length: 15,
        append_header: true,
        header_start_row: 1,
        header_end_row: 1
    });
    const [strategies, setStrategies] = useState(initialStrategies);

    // Update rules when strategies change
    useEffect(() => {
        const [separator, separatorRule] = strategies.reduce(([_separator, _separatorRule], strategy) => {
            const { regex, position } = strategy;
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
        setRules({
            knowledgeId: kid,
            fileList: resultFiles.map(file => ({
                id: file.id,
                filePath: file.file_path,
                fileName: file.fileName,
                suffix: file.suffix,
                fileType: file.fileType,
                excelRule: file.fileType === 'table' ? {
                    ...cellGeneralConfig
                } : {}
            })),
            separator: ['\\n\\n', '\\n'],
            separatorRule: ['after', 'after'],
            chunkSize: "1000",
            chunkOverlap: "100",
            retainImages: true,
            enableFormula: true,
            forceOcr: true,
            pageHeaderFooter: true
        });
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
