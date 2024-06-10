import { ArrowLeft } from "lucide-react";
import { useCallback, useContext, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import ShadTooltip from "../../components/ShadTooltipComponent";
import { Button } from "../../components/bs-ui/button";
import { Label } from "../../components/bs-ui/label";
import { alertContext } from "../../contexts/alertContext";
import { TabsContext } from "../../contexts/tabsContext";
import { readFlowsFromDatabase } from "../../controllers/API/flow";
import { Select, SelectContent, SelectGroup, SelectTrigger, SelectItem, SelectValue } from "../../components/bs-ui/select";
import { useDropzone } from "react-dropzone";
import { UploadIcon } from "@/components/bs-icons/upload";
import { QuestionMarkIcon } from "@/components/bs-icons/questionMark";
import { AssistantItemDB, getAssistantsApi } from "@/controllers/API/assistant";
import { debounce, find } from "lodash";
import { TypeModal } from "@/utils";
import PromptAreaComponent from "./PromptCom";
import defaultPrompt from "./defaultPrompt";
import { createEvaluationApi } from "@/controllers/API/evaluate";
import { TooltipProvider,Tooltip, TooltipTrigger, TooltipContent } from "../../components/bs-ui/tooltip";
import { Input } from "@/components/bs-ui/input";
import { SelectViewport } from "@radix-ui/react-select";


export default function EvaluatingCreate() {
    const { t } = useTranslation()


    const { id } = useParams()
    const { flow: nextFlow } = useContext(TabsContext);
    const { setErrorData } = useContext(alertContext);
    const flow = useMemo(() => {
        return id ? nextFlow : null
    }, [nextFlow])
    const [selectedType, setSelectedType] = useState<'flow' | 'assistant' | ''>('')
    const [selectedKeyId, setSelectedKeyId] = useState('')
    const [selectedVersion, setSelectedVersion] = useState('')
    const [searchName, setSearchName] = useState('')
    const [dataSource, setDataSource] = useState([])
    const [prompt, setPrompt]=useState(defaultPrompt)
    const [fileName, setFileName] =useState('')
    

    const [loading, setLoading] = useState(false)
    const fileRef = useRef(null)

    const onDrop = (acceptedFiles) => {
        fileRef.current = acceptedFiles[0]
        const names = acceptedFiles[0].name
        setFileName(names)
    }

    const { getRootProps, getInputProps } = useDropzone({
        accept: {
            'application/*': ['.csv']
        },
        useFsAccessApi: false,
        onDrop,
        maxFiles: 1
    });
        


    // 校验
    const [error, setError] = useState({ name: false, desc: false }) // 表单error信息展示

    const navigate = useNavigate()

    const handleCreateEvaluation = async () => {
        const errorlist = []
        if(!selectedType) errorlist.push(t('evaluation.enterExecType'))
        if(!selectedKeyId) errorlist.push(t('evaluation.enterUniqueId'))
        if(selectedType === 'flow' && !selectedVersion) errorlist.push(t('evaluation.enterVersion'))
        if(!fileRef.current) errorlist.push(t('evaluation.enterFile'))
        if(!prompt) errorlist.push(t('evaluation.enterPrompt'))
        
        if (errorlist.length) return handleError(errorlist)
        setLoading(true)
        try {
            await createEvaluationApi({
                exec_type: selectedType,
                unique_id: selectedKeyId,
                version: selectedVersion,
                prompt,
                file: fileRef.current
            })
            navigate(-1)
        } finally {
            setLoading(false)
        }
    }

    const handleError = (list) => {
        setErrorData({
            title: t('prompt'),
            list
        });
    }

    // 助手技能发生变化
    const handleTypeChange = (type) => {
        setSearchName('')
        if(type === 'flow') {
            readFlowsFromDatabase(1,100,'').then(_flow => {
                setDataSource(_flow.data)
            })
        } else if(type === 'assistant') {
            getAssistantsApi(1, 100, '').then(data => {
                setDataSource((data as any).data as AssistantItemDB[])
            })
        }
    }

    const handleDownloadTemplate = () => {
        const link = document.createElement('a');
        link.href = '/template.csv'; // 文件路径
        link.download = 'template.csv'; // 下载时的文件名
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    const DebouncedSearch = useCallback(
        debounce((searchQuery) => {
            if(selectedType === 'flow') {
                readFlowsFromDatabase(1, 100, searchQuery).then(_flow => {
                    setDataSource(_flow.data)
                })
            } else if(selectedType === 'assistant') {
                getAssistantsApi(1, 100, searchQuery).then(data => {
                    setDataSource((data as any).data as AssistantItemDB[])
                })
            }
        }, 500),
        []
    );

    const handleInputChange = (event) => {
        const newName = event.target.value;        
        setSearchName(newName);
        DebouncedSearch(newName);
    };

    return <div className="relative box-border h-full overflow-auto">
        <div className="p-6 pb-48 h-full overflow-y-auto">
            <div className="flex justify-between w-full">
                <ShadTooltip content={t('back')} side="right">
                    <button className="extra-side-bar-buttons w-[36px]" onClick={() => navigate(-1)}>
                        <ArrowLeft strokeWidth={1.5} className="side-bar-button-size" />
                    </button>
                </ShadTooltip>
            </div>
            {/* form */}
            <div className="pt-6">
                <p className="text-center text-2xl">{t('evaluation.createTitle')}</p>
                <div className="w-full max-w-2xl mx-auto mt-4">
                    {/* base form */}
                    <div className="w-full overflow-hidden transition-all px-1">
                        <div className="mt-4 flex items-center justify-between">
                            <Label className="w-[180px] text-right whitespace-nowrap">{t('evaluation.selectLabel')}</Label>
                            <div className="flex-1 flex gap-2">
                                <Select value={selectedType} onValueChange={(value)=> {
                                    setSelectedType(value as any)
                                    setSelectedKeyId('')
                                    handleTypeChange(value)
                                }}>
                                    <SelectTrigger>
                                        <SelectValue className={`mt-2 ${error.name && 'border-red-400'} w-auto`} placeholder={t('evaluation.selectPlaceholder')} />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectGroup>
                                            <SelectItem value="flow">{t('build.skill')}</SelectItem>
                                            <SelectItem value="assistant">{t('build.assistant')}</SelectItem>
                                        </SelectGroup>
                                    </SelectContent>
                                </Select>
                                <Select value={selectedKeyId} onValueChange={(id)=> setSelectedKeyId(id)} onOpenChange={()=>{
                                    if(!selectedType) return handleError([t('evaluation.enterExecType')])
                                }}>
                                    <SelectTrigger slot="" className="max-w-[200px]">
                                        <SelectValue className={`mt-2 max-w-[200px] ${error.name && 'border-red-400'}`} placeholder={t('evaluation.selectPlaceholder')} />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectViewport>
                                            <Input value={searchName} onChange={handleInputChange} className={`mt-2 max-w-[200px] ${error.name && 'border-red-400'}`} placeholder={t('evaluation.selectInputPlaceholder')} />
                                            <SelectGroup>
                                                {dataSource.map(item =>{
                                                    return <SelectItem value={item.id}>{item.name}</SelectItem>
                                                })}
                                            </SelectGroup>
                                        </SelectViewport>
                                    </SelectContent>
                                </Select>
                                {selectedType === 'flow' &&
                                <Select value={selectedVersion} onValueChange={(version)=>setSelectedVersion(version)} onOpenChange={()=>{
                                    if(!selectedKeyId) return handleError([t('evaluation.enterUniqueId')])
                                }}>
                                    <SelectTrigger className="min-w-[50px]">
                                        <SelectValue className={`mt-2 ${error.name && 'border-red-400'}`} placeholder={t('evaluation.selectPlaceholder')} />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectGroup>
                                            {find(dataSource,{'id':selectedKeyId})?.version_list?.map(item =>{
                                                return <SelectItem value={item.id}>{item.name}</SelectItem>
                                            })}
                                        </SelectGroup>
                                    </SelectContent>
                                </Select>}
                            </div>
                        </div>
                        <div className="mt-4 flex items-center">
                            <div className="min-w-[180px] text-right">
                                <Label className="whitespace-nowrap">{t('evaluation.dataLabel')}</Label>
                            </div>
                            <div className="flex-1 flex items-center justify-between">
                                <div {...getRootProps()} className="flex-1 flex items-center w-0">
                                    <input {...getInputProps()} />
                                    <div className="flex justify-center items-center cursor-pointer hover:border-primary py-[8px] px-[12px] border rounded-md">
                                        <UploadIcon className="group-hover:text-primary" />
                                        <span className="whitespace-nowrap">{t('code.uploadFile')}</span>
                                    </div>
                                    {fileName && <div className="ml-2 truncate">{fileName}</div>}
                                    <Label className="whitespace-nowrap">&nbsp;{t('evaluation.fileExpandName')}&nbsp;csv</Label>
                                </div>
                                <Button className="w-[80px] ml-2" variant="link" onClick={handleDownloadTemplate}>{t('evaluation.downloadTemplate')}</Button>
                            </div>
                        </div>
                        <div className="mt-4 flex items-center justify-between">
                            <div className="min-w-[180px] text-right">
                                <Label className="whitespace-nowrap flex items-center justify-end">
                                <TooltipProvider>
                                    <Tooltip>
                                        <TooltipTrigger asChild>
                                            <Button variant="link" className="p-0 mr-1">
                                                <QuestionMarkIcon
                                                    className={"w-[15px] icons-parameters-comp hover:text-accent-foreground"}
                                                />
                                            </Button>
                                        </TooltipTrigger>
                                        <TooltipContent>
                                        <p>{t('evaluation.tooltip')}</p>
                                        </TooltipContent>
                                    </Tooltip>
                                </TooltipProvider>
                                    
                                    {t('evaluation.promptLabel')}
                                </Label>
                            </div>
                            <div className="flex-1" style={{ width: 'calc(100% - 180px)'}}>
                                <PromptAreaComponent
                                    field_name={'prompt'}
                                    editNode={false}
                                    disabled={false}
                                    type={TypeModal.TEXT}
                                    value={prompt}
                                    onChange={(t: string) => {
                                        setPrompt(t);
                                    }}
                                />
                            </div>
                        </div>

                        <div className="flex mt-8">
                            <div className="min-w-[180px]"></div>
                            <div className="flex-1 flex gap-4">
                                <Button disabled={loading} className="extra-side-bar-save-disable flex-1" onClick={handleCreateEvaluation}>
                                    {t('evaluation.create')}
                                </Button>
                                <Button disabled={loading} className="flex-1" variant="outline" onClick={() => navigate(-1)}>
                                    {t('evaluation.cancel')}
                                </Button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
};
