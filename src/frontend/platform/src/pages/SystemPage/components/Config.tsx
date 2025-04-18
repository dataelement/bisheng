import { useContext, useEffect, useRef, useState } from "react";
import AceEditor from "react-ace";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/bs-ui/button";
import { getSysConfigApi, setSysConfigApi } from "../../../controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { locationContext } from "@/contexts/locationContext";
import { useToast } from "@/components/bs-ui/toast/use-toast";

export default function Config() {
    const { toast, message } = useToast()
    const { reloadConfig } = useContext(locationContext)

    const [config, setConfig] = useState('')

    const { t } = useTranslation()

    useEffect(() => {
        captureAndAlertRequestErrorHoc(getSysConfigApi().then(jsonstr => {
            setConfig(jsonstr)
            codeRef.current = jsonstr
        }))
    }, [])

    const handleSave = () => {
        if (validataRef.current.length) {
            return toast({
                variant: 'error',
                title: `yaml${t('formatError')}`,
                description: validataRef.current.map(el => el.text)
            })
        }

        captureAndAlertRequestErrorHoc(setSysConfigApi({ data: codeRef.current }).then(res => {
            message({
                variant: 'success',
                title: t('prompt'),
                description: t('saved')
            })
            setConfig(codeRef.current)

            // 更新配置信息
            reloadConfig()
        }))
    }

    const codeRef = useRef('')
    const validataRef = useRef([])
    return <div className=" max-w-[80%] mx-auto">
        <p className="font-bold mt-8 mb-2">{t('system.parameterConfig')}</p>
        <AceEditor
            value={config || ''}
            mode="yaml"
            theme={"twilight"}
            highlightActiveLine={true}
            showPrintMargin={false}
            fontSize={14}
            showGutter
            enableLiveAutocompletion
            name="CodeEditor"
            onChange={(value) => codeRef.current = value}
            onValidate={(e) => validataRef.current = e}
            className="h-[70vh] w-full rounded-lg border-[1px] border-border custom-scroll"
        />
        <div className="flex justify-center mt-8">
            <Button className=" h-10 w-[120px] px-24 text-[#fff]" onClick={handleSave}>{t('save')}</Button>
        </div>
    </div>
};