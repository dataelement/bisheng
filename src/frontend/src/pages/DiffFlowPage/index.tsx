import { PlusIcon } from "@/components/bs-icons/plus"
import { Button } from "@/components/bs-ui/button"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { getFlowVersions } from "@/controllers/API/flow"
import { useDiffFlowStore } from "@/store/diffFlowStore"
import { FlowVersionItem } from "@/types/flow"
import { ChevronLeft } from "lucide-react"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { useNavigate, useParams } from "react-router-dom"
import Component from "./components/Component"
import RunTest from "./components/RunTest"

export default function index(params) {
    const { t } = useTranslation()
    // 技能 id, 版本id, 组件id
    const { id, vid, cid } = useParams()
    const navigate = useNavigate()
    const { message } = useToast()

    const versions = useVersions(id)

    const { mulitVersionFlow, removeVersionFlow, initFristVersionFlow, addEmptyVersionFlow, addVersionFlow } = useDiffFlowStore()
    useEffect(() => {
        initFristVersionFlow(vid)
    }, [])

    const handleAddVersion = () => {
        if (mulitVersionFlow.length >= 4) return message({
            title: '',
            description: t('test.maxAddVersions'),
            variant: 'error',
        })
        addEmptyVersionFlow()
    }

    console.log('mulitVersionFlow', mulitVersionFlow);


    return <div className="bg-gray-100 dark:bg-[#111] h-full relative">
        {/* header */}
        <div className="absolute top-0 w-full h-14 flex justify-between items-center border-b px-4 bg-[#fff] dark:bg-[#222]">
            <Button variant="outline" size="icon" onClick={() => navigate(-1)}><ChevronLeft className="h-4 w-4" /></Button>
            <span>{t('test.versionEvaluation')}</span>
            <Button type="button" onClick={handleAddVersion}>
                <PlusIcon className="text-primary" />
                {t('test.addVersion')}({mulitVersionFlow.length}/4)
            </Button>
        </div>

        {/* content */}
        <div className="h-full pt-14 overflow-y-auto">
            {/* comps */}
            <div className={`grid gap-4 mt-4 px-4 box-border ${mulitVersionFlow.length === 3 ? 'grid-cols-3' : 'grid-cols-2'}`}>
                {
                    mulitVersionFlow.map((version, index) => (
                        <Component
                            key={index}
                            compId={cid}
                            options={versions}
                            disables={mulitVersionFlow.map((v) => v?.id)}
                            version={version}
                            className={''}
                            onChangeVersion={(vid) => addVersionFlow(vid, index)}
                            onClose={() => removeVersionFlow(index)}
                        />
                    ))
                }
            </div>
            {/* run test */}
            <RunTest nodeId={cid}></RunTest>
        </div>
    </div>
};



const useVersions = (flowId) => {
    const [versions, setVersions] = useState<FlowVersionItem[]>([])
    useEffect(() => {
        getFlowVersions(flowId).then(({ data }) => {
            setVersions(data)
        })
    }, [])

    return versions
}