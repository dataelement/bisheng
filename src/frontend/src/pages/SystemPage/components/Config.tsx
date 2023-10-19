import { useContext, useEffect, useRef, useState } from "react";
import { Button } from "../../../components/ui/button";
import AceEditor from "react-ace";
import { getSysConfigApi, setSysConfigApi } from "../../../controllers/API";
import { alertContext } from "../../../contexts/alertContext";

export default function Config() {
    const { setErrorData, setSuccessData } = useContext(alertContext);
    const [config, setConfig] = useState('')

    useEffect(() => {
        getSysConfigApi().then(res => {
            setConfig(res.data)
            codeRef.current = res.data
        })
    }, [])

    const handleSave = () => {
        if (validataRef.current.length) {
            return setErrorData({
                title: "yaml格式错误",
                list: validataRef.current.map(el => el.text),
            });
        }

        setSysConfigApi({ data: codeRef.current }).then(res => {
            setSuccessData({ title: '保存成功' })
        })
    }

    const codeRef = useRef('')
    const validataRef = useRef([])
    return <div className=" max-w-[600px] mx-auto">
        <p className="font-bold mt-8 mb-2">参数配置</p>
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
            className="h-[600px] w-full rounded-lg border-[1px] border-border custom-scroll"
        />
        <div className="flex justify-center mt-8">
            <Button className=" rounded-full px-24" onClick={handleSave}>保存</Button>
        </div>
    </div>
};
