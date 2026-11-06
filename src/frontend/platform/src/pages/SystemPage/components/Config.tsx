// @ts-strict-ignore
import { Button, notification, toast } from '@bisheng/ui';
import { useContext, useEffect, useRef, useState } from "react";
import AceEditor from "react-ace";
import { useTranslation } from "react-i18next";

import { getSysConfigApi, setSysConfigApi } from "../../../controllers/API/user";
import { showApiError } from "../../../controllers/request";
import { locationContext } from "@/contexts/locationContext";


export default function Config() {

    const { reloadConfig } = useContext(locationContext)

    const [config, setConfig] = useState('')
    const [loaded, setLoaded] = useState(false)

    const { t } = useTranslation()

    useEffect(() => {
        getSysConfigApi().then(jsonstr => {
            setConfig(jsonstr)
            codeRef.current = jsonstr
            setLoaded(true)
        }).catch(showApiError)
    }, [])

    const handleSave = () => {
        if (!loaded) return
        if (validataRef.current.length) {
            return notification.open({ type: 'error', title: String(`yaml${t('formatError')}`), description: (validataRef.current.map(el => el.text)).filter(Boolean).join('\n') })
        }

        setSysConfigApi({ data: codeRef.current }).then(res => {
            toast.show({ type: 'success', message: [String(t('prompt') ?? ''), String(t('saved') ?? '')].filter(Boolean).join('\n') })
            setConfig(codeRef.current)

            // 更新配置信息
            reloadConfig()
        }).catch(showApiError)
    }

    const codeRef = useRef('')
    const validataRef = useRef([])
    return <div className="flex h-full max-w-[80%] mx-auto flex-col pt-6 pb-4">
        <p className="font-bold mb-2 shrink-0">{t('system.parameterConfig')}</p>
        <AceEditor
            width="100%"
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
            className="min-h-0 w-full flex-1 rounded-lg border-[1px] border-border custom-scroll"
        />
        <div className="flex justify-center mt-4 shrink-0">
            <Button disabled={!loaded} onClick={handleSave}>{t('save')}</Button>
        </div>
    </div>
};
