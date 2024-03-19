import { useContext, useEffect, useRef, useState } from "react";
import AceEditor from "react-ace";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/ui/button";
import { alertContext } from "../../../contexts/alertContext";
import { getSysConfigApi, setSysConfigApi } from "../../../controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";

export default function Config() {
    const { setErrorData, setSuccessData } = useContext(alertContext);
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
            return setErrorData({
                title: `yaml${t('formatError')}`,
                list: validataRef.current.map(el => el.text),
            });
        }

        captureAndAlertRequestErrorHoc(setSysConfigApi({ data: codeRef.current }).then(res => {
            setSuccessData({ title: t('success') })
            setConfig(codeRef.current)
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
            <Button className=" rounded-full px-24" onClick={handleSave}>{t('save')}</Button>
        </div>
    </div>
};

