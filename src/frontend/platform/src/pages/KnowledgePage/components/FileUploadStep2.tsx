import { LoadIcon } from "@/components/bs-icons";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { retryKnowledgeFileApi, subUploadLibFile } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import SplitRules from "@/pages/KnowledgePage/components/splitRules"
import ExcelList from "@/pages/KnowledgePage/components/ExcelList"
const initialStrategies = [
    { id: '1', regex: '\\n\\n', position: 'after' },
    // { id: '2', regex: '\\n', position: 'after' }
];

interface IProps {
    fileInfo: { fileCount: number, files: any, failFiles: any }
    setShowSecondDiv: (show:boolean) => void
    onPrev: () => void
    onPreview: (data: any, files: any) => void
    onChange: () => void
}

export default function FileUploadStep2({ fileInfo, onPrev, onPreview, onChange ,setShowSecondDiv}: IProps) {
    const { id: kid } = useParams()
    const { t } = useTranslation('knowledge')

    const chunkType = useRef('smart')
    // 切分
    const [strategies, setStrategies] = useState(initialStrategies);
    // size
    const [size, setSize] = useState('1000')
    // 符号
    const [overlap, setOverlap] = useState('100')
      // 分段行
      const [burst, setBurst] = useState('15')
      // 行
      const [gauge, setGauge] = useState('1')
      const [rowend, setRowend] = useState('2')
      //为分段添加表头勾选框
      const [appendh,setAppendh] = useState(false)
      //保留文档图片
      const [retain,setRetain] = useState(false)
      //强制开启ocr
      const [forocr,setForocr] = useState(false)
      //开启公式识别
      const [formula,setFormula] = useState(false)
      //过滤页眉页脚
      const [filhf,setFilhf] = useState(false)
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
              appendh:false,
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
    }, [strategies, size, overlap])

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
        const generateExcelRules = () => 
            Object.entries(fileConfigs).reduce((acc, [idi, config]) => ({
              ...acc,
              [`uuid${idi}`]: {
                slice_length: config.burst,
                append_header: config.appendh,
                header_start_row: config.gauge,
                header_end_row: config.rowend
              }
            }), {});
        const handleFileParams = chunkType.current === 'chunk' ? {
            // excel_rules
            excel_rules: generateExcelRules()
            
        } : {
            separator,
            separator_rule,
            chunk_size: size,
            chunk_overlap: overlap,
            retain_images:retain,
            enable_formula: formula,
            force_ocr: forocr,
            filter_page_header_footer: filhf,
        }
        return {
            knowledge_id: Number(kid),
            ...handleFileParams
        }
    }
    const handleSubmit = async () => {
        const { fileCount, failFiles } = fileInfo
        const params = {
            ...getParams(size, overlap),
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
        const params = { ...getParams(size, overlap), file_objs: objs }
        captureAndAlertRequestErrorHoc(retryKnowledgeFileApi(params).then(res => {
            setRepeatFiles([])
            setRetryLoad(false)
            // onNext()
            message({ variant: 'success', description: t('addSuccess') });
            navaigate(-1)
        }))
    }

    // 预览
    const handlePreview = () => {
        const params = getParams(size, overlap)
        console.log(params)
        setShowSecondDiv(true); 
        onPreview(params, fileInfo.files)
    }

    return <div className="flex flex-col">
        <div className="flex items-center gap-2 my-6 px-12 text-sm font-bold max-w-96">
            <span>①{t('uploadFile')}</span>
            <div className="h-[1px] flex-grow bg-gray-300"></div>
            <span className="text-primary">②{t('docProcessingStrategy')}</span>
        </div>

        <Tabs defaultValue="smart" className="w-full mt-4 text-center" onValueChange={(val) => chunkType.current = val}>
            <TabsList className="a mx-auto">
                <TabsTrigger value="smart" className="roundedrounded-xl">{t('defaultStrategy')}</TabsTrigger>
                <TabsTrigger value="chunk">{t('customStrategy')}</TabsTrigger>
            </TabsList>
            <ExcelList
              strategies={strategies}
              setStrategies={setStrategies}
              burst={burst}
              setBurst={setBurst}
              gauge={gauge}
              setGauge={setGauge}
              rowend={rowend}
              setRowend={setRowend}
              appendh={appendh}
              setAppendh={setAppendh}
              t={t}
              handlePreview={handlePreview}
              onChange={onChange}
              dataArray={dataArray}
              fileConfigs={fileConfigs}
              setFileConfigs={setFileConfigs}
              updateConfig={updateConfig}
            />
            <SplitRules
                strategies={strategies}
                setStrategies={setStrategies}
                size={size}
                setSize={setSize}
                overlap={overlap}
                setOverlap={setOverlap}
                t={t}
                handlePreview={handlePreview}
                retain={retain}
                setRetain={setRetain}
                forocr={forocr}
                setForocr={setForocr}
                formula={formula}
                setFormula={setFormula}
                filhf={filhf}
                setFilhf={setFilhf}
            />
           
        </Tabs>
        
        <div className="flex justify-end mt-8 gap-4">
            <Button className="h-8" variant="outline" onClick={onPrev}>{t('previousStep')}</Button>
            <Button disabled={loading} className="h-8" onClick={handleSubmit}>
                {loading && <LoadIcon />} {t('nextStep')}
            </Button>
            
        </div>
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
