import { Label } from "@/components/bs-ui/label";
import { Switch } from "@/components/bs-ui/switch";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import AceEditor from "react-ace";
import Vditor from 'vditor';
import 'vditor/dist/index.css';

const VditorEditor = forwardRef(({ markdown, hidden }, ref) => {
    const vditorRef = useRef(null);
    const readyRef = useRef(false);

    useEffect(() => {
        if (!hidden && vditorRef.current && readyRef.current) {
            vditorRef.current.setValue(markdown);
        }
    }, [markdown, hidden])

    useImperativeHandle(ref, () => ({
        getResult() {
            return vditorRef.current.getValue()
        }
    }))

    useEffect(() => {
        vditorRef.current = new Vditor('vditor', {
            height: '100%',
            toolbarConfig: {
                hide: true,
                pin: true,
            },
            mode: 'ir',  // 'sv' for split view, 'ir' for instant rendering
            preview: {
                markdown: {
                    toc: true,
                    mark: true,
                },
            },
            cache: {
                enable: false,
            },
            after: () => {
                console.log('Vditor is ready');
                vditorRef.current.setValue(markdown);
                readyRef.current = true;
            },
        });

        return () => {
            vditorRef.current.destroy();
        };
    }, []);

    // vditorRef.current.getValue()
    // vditorRef.current.getHTML();
    // vditorRef.current.getText();
    return <div id="vditor" className={hidden ? 'hidden' : ''}></div>;
});

const AceEditorCom = ({ markdown, hidden, onChange }) => {

    if (hidden) return null

    return <AceEditor
        value={markdown || ''}
        mode="markdown"
        theme={"twilight"}
        highlightActiveLine={true}
        showPrintMargin={false}
        fontSize={14}
        showGutter
        enableLiveAutocompletion
        name="CodeEditor"
        onChange={onChange}
        onValidate={(e) => console.error('ace validate :>> ', e)}
        className="h-full w-full rounded-lg border-[1px] border-border custom-scroll"
    />
}

export default forwardRef(function Markdown({ value }, ref) {
    const [val, setValue] = useState('')
    const [isAce, setIsAce] = useState(true)
    useEffect(() => {
        setValue(value)
    }, [value])

    const vditorRef = useRef(null)

    useImperativeHandle(ref, () => ({
        getValue() {
            const _value = isAce ? val : vditorRef.current.getResult()
            return _value
        }
    }))

    const hangleCheckChagne = (checked) => {
        if (!checked) {
            setValue(vditorRef.current.getResult())
        }
        setIsAce(!checked)
    }

    {/* markdown */ }
    return <div >
        <div className="flex justify-between mb-2">
            <Label className="bisheng-label"><span className="text-red-500">*</span>分段内容</Label>
            <div className="flex items-center gap-2"><Label>markdown预览</Label><Switch checked={!isAce} onCheckedChange={hangleCheckChagne} /></div>
        </div>
        <div className="border mb-2 h-[calc(100vh-140px)]">
            {/* 编辑器 */}
            <AceEditorCom hidden={!isAce} markdown={val} onChange={setValue} />
            <VditorEditor ref={vditorRef} hidden={isAce} markdown={val} />
        </div>
    </div >
});
