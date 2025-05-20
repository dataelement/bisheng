import { LoadIcon } from "@/components/bs-icons";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { retryKnowledgeFileApi, subUploadLibFile } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import FilesDoc from "@/pages/KnowledgePage/components/FilesDoc"
import TabularDoc from "@/pages/KnowledgePage/components/TabularDoc"
import YuLan from "./YuLan";
const initialStrategies = [
    { id: '1', regex: '\\n\\n', position: 'after' },
    // { id: '2', regex: '\\n', position: 'after' }
];
interface FileItem {
    id: string;
    fileName: string;
    file_path: string;
    fileType: 'table' | 'file';
}
interface IProps {
    fileInfo: { fileCount: number, files: any, failFiles: any }
    setShowSecondDiv: (show: boolean) => void
    onPrev: () => void
    onPreview: (data: any, files: any) => void
    onChange: () => void
    resultFiles: FileItem[]
}

export default function FileUploadStep2({ fileInfo, onPrev, resultFiles, onPreview, onChange }: IProps) {
    const { id: kid } = useParams()
    const { t } = useTranslation('knowledge')

    // 初始化时根据文件类型设置 chunkType
    const chunkType = useRef(
        resultFiles.some(file => file.fileType === 'table') ? 'chunk' : 'smart'
    )

    // 当 resultFiles 变化时检查是否需要更新 chunkType
    useEffect(() => {
        if (resultFiles.some(file => file.fileType === 'table')) {
            chunkType.current = 'chunk'
        } else {
            chunkType.current = 'smart'
        }
    }, [resultFiles])
    const fileNames = useMemo(() => resultFiles.map(file => file.fileName), [resultFiles])
    console.log("fileNames:", fileNames, Array.isArray(fileNames)); // 检查是否是数组

    const displayMode = useMemo(
        () => {
            const hasTableFiles = resultFiles.some(file => file.fileType === 'table');
            const hasDocumentFiles = resultFiles.some(file => file.fileType === 'file');
            return hasTableFiles && !hasDocumentFiles ? 'only-tables' :
                !hasTableFiles && hasDocumentFiles ? 'only-documents' :
                    'mixed';
        }, [resultFiles]
    )

    console.log(displayMode);


    // 切分
    const [strategies, setStrategies] = useState(initialStrategies);
    const [documentSettings, setDocumentSettings] = useState({
        size: '1000',        // 文档大小
        overlap: '100',      // 重叠符号
        burst: '15',         // 分段行数
        gauge: '1',          // 起始行
        rowend: '2',         // 结束行
        appendh: false,      // 添加表头
        retain: false,       // 保留图片
        forocr: false,       // 强制OCR
        formula: false,      // 公式识别
        filhf: false         // 过滤页眉页脚
    });
    const [showSecondDiv, setShowSecondDiv] = useState(false);
    // 统一处理设置变更
    const handleSettingChange = (key, value) => {
        setDocumentSettings(prev => ({
            ...prev,
            [key]: value
        }));
        onChange(); // 通知父组件有变更
    };
    const [dataArray, setDataArray] = useState([
        { idi: 1, name: 'Excel文件1.xlsx' },
        { idi: 2, name: '报表数据2.xlsx' },
        { idi: 3, name: '财务记录3.xlsx' },
        { idi: 4, name: '项目计划4.xlsx' },
        { idi: 5, name: '项目计划4.xlsx' },
        { idi: 6, name: '项目计划4.xlsx' }
    ]);
    const [fileConfigs, setFileConfigs] = useState(
        dataArray.reduce((acc, item) => ({
            ...acc,
            [item.idi]: {
                appendh: false,
                burst: 5,
                gauge: 1,
                rowend: 2
            }
        }), {})
    );
    const updateConfig = (fileId, key, value) => {
        setFileConfigs(prev => ({
            ...prev,
            [fileId]: { ...prev[fileId], [key]: value }
        }));
    };
    useEffect(() => {
        onChange()
    }, [strategies])

    const [loading, setLoading] = useState(false)
    const { message } = useToast()
    const navaigate = useNavigate()
    //预览分段结果接口
    const getParams = (size, overlap) => {
        const [separator, separator_rule] = strategies.reduce((res, item) => {
            const { regex, position } = item
            res[0].push(regex)
            res[1].push(position)
            return res
        }, [[], []])

        // 判断是否是表格文件（根据 resultFiles 中的 fileType）
        const isTableFile = resultFiles.some(file => file.fileType === 'table')

        const generateExcelRules = () =>
            Object.entries(fileConfigs).reduce((acc, [idi, config]) => ({
                ...acc,
                [`uuid${idi}`]: {
                    slice_length: config.burst,
                    append_header: config.appendh,
                    header_start_row: config.gauge,
                    header_end_row: config.rowend
                }
            }), {})
        console.log(isTableFile, chunkType.current);


        // 如果是表格文件，只返回第一段参数
        if (isTableFile && chunkType.current === 'chunk') {
            return {
                knowledge_id: Number(kid),
                excel_rules: generateExcelRules()
            }
        }
        return {
            knowledge_id: Number(kid),
            separator,
            separator_rule,
            chunk_size: documentSettings.size,
            chunk_overlap: documentSettings.overlap,
            retain_images: documentSettings.retain,
            enable_formula: documentSettings.formula,
            force_ocr: documentSettings.forocr,
            filter_page_header_footer: documentSettings.filhf,
            ...(chunkType.current === 'chunk' ? { excel_rules: generateExcelRules() } : {})
        }
    }
    const handleSubmit = async () => {
        const { fileCount, failFiles } = fileInfo
        console.log(fileInfo);

        const params = {
            ...getParams(documentSettings.size, documentSettings.overlap),
            file_list: fileInfo.files.map(file => ({ file_path: file.path }))
        }

        setLoading(true)
        await captureAndAlertRequestErrorHoc(subUploadLibFile(params).then(res => {
            const _repeatFiles = res.filter(e => e.status === 3)
            if (_repeatFiles.length) {
                setRepeatFiles(_repeatFiles)
            } else {
                failFiles.length ? bsConfirm({
                    desc: <div>
                        <p>{t('fileUploadResult', { total: fileCount, failed: failFiles.length })}</p>
                        <div className="max-h-[160px] overflow-y-auto no-scrollbar">
                            {failFiles.map(el => <p className=" text-red-400" key={el.id}>{el.name}</p>)}
                        </div>
                    </div>,
                    onOk(next) {
                        next()
                        navaigate(-1)
                    }
                }) : (message({ variant: 'success', description: t('addSuccess') }), navaigate(-1))
            }
        }))
        setLoading(false)
    }

    // 重复文件列表
    const [repeatFiles, setRepeatFiles] = useState([])
    // 重试解析
    const [retryLoad, setRetryLoad] = useState(false)
    const handleRetry = (objs) => {
        setRetryLoad(true)
        const params = { ...getParams(documentSettings.size, documentSettings.overlap), file_objs: objs }
        captureAndAlertRequestErrorHoc(retryKnowledgeFileApi(params).then(res => {
            setRepeatFiles([])
            setRetryLoad(false)
            // onNext()
            message({ variant: 'success', description: t('addSuccess') });
            navaigate(-1)
        }))
    }
    const handlePreview = () => {
        // 预览参数
        const params = getParams(documentSettings.size, documentSettings.overlap)
        console.log('Preview params:', params)

        setShowSecondDiv(true)
        onPreview(params, fileInfo)
    }
    return <div className="flex flex-row">
        <div className={showSecondDiv ? "w-1/2 pr-2 overflow-y-auto" : "w-full overflow-y-auto"}>
            <Tabs defaultValue={displayMode === 'only-tables' ? 'chunk' : 'smart'} className="w-full mt-4 text-center" onValueChange={(val) => chunkType.current = val}>
                {displayMode === 'mixed' && <TabsList className="a mx-auto">
                    <TabsTrigger value="smart" className="roundedrounded-xl">{t('defaultStrategy')}</TabsTrigger>
                    <TabsTrigger value="chunk">{t('customStrategy')}</TabsTrigger>
                </TabsList>
                }
                {/* 表格文档设置 */}
                {displayMode !== 'only-documents' && <TabularDoc
                    strategies={strategies}
                    settings={documentSettings}
                    onSettingChange={handleSettingChange}
                    t={t}
                    onChange={onChange}
                    handlePreview={handlePreview}
                    dataArray={dataArray}
                    fileConfigs={fileConfigs}
                    setFileConfigs={setFileConfigs}
                    updateConfig={updateConfig}
                />
                }
                {/* 文件文档设置 */}
                {displayMode !== 'only-tables' && <FilesDoc
                    onChange={onChange}
                    strategies={strategies}
                    setStrategies={setStrategies}
                    settings={documentSettings}
                    onSettingChange={handleSettingChange}
                    t={t}
                    handlePreview={handlePreview}
                />
                }
            </Tabs>
        </div>
        {/* 右侧预览区域 */}
        {showSecondDiv && (
            <div className="w-1/2 pl-2 overflow-y-auto">
                <YuLan fileNames={fileNames}
                />
            </div>
        )}


        {/* <div className="flex justify-end mt-8 gap-4">
    <Button className="h-8" variant="outline" onClick={onPrev}>{t('previousStep')}</Button>
    <Button disabled={loading} className="h-8" onClick={handleSubmit}>
        {loading && <LoadIcon />} {t('submit')}
    </Button>
    <Button className="h-8" id={'preview-btn'} onClick={handlePreview}>{t('previewResults')}</Button>
</div> */}

        {/* 重复文件提醒 */}
        <Dialog open={!!repeatFiles.length} onOpenChange={b => !b && setRepeatFiles([])}>
            <DialogContent className="sm:max-w-[425px]">
                <DialogHeader>
                    <DialogTitle>{t('modalTitle')}</DialogTitle>
                    <DialogDescription>{t('modalMessage')}</DialogDescription>
                </DialogHeader>
                <ul className="overflow-y-auto max-h-[400px]">
                    {repeatFiles.map(el => (
                        <li key={el.id} className="py-2 text-red-500">{el.remark}</li>
                    ))}
                </ul>
                <DialogFooter>
                    <Button className="h-8" variant="outline" onClick={() => { setRepeatFiles([]); navaigate(-1) }}>{t('keepOriginal')}</Button>
                    <Button className="h-8" disabled={retryLoad} onClick={() => handleRetry(repeatFiles)}>
                        {retryLoad && <span className="loading loading-spinner loading-xs"></span>}{t('override')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    </div>
};
