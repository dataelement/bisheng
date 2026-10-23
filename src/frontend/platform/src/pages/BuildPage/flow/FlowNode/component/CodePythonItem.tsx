import { Button } from '@bisheng/ui';

import { Dialog,DialogContent,DialogHeader,DialogTitle,DialogTrigger } from "@/components/bs-ui/dialog";
import { darkContext } from "@/contexts/darkContext";
import { Outlined } from "bisheng-icons";

import { useContext,useState } from "react";
import AceEditor from "react-ace";

export default function CodePythonItem({ data, onChange, i18nPrefix }) {
    const { dark } = useContext(darkContext);
    const [code, setCode] = useState(data.value);

    return <div className="relative min-w-0">
        <AceEditor
            width="100%"
            height="160px"
            value={data.value}
            mode="python"
            highlightActiveLine={true}
            showPrintMargin={false}
            fontSize={14}
            showGutter
            enableLiveAutocompletion
            theme={dark ? "twilight" : "github"}
            name="CodeEditor"
            onChange={(value) => {
                setCode(value);
                onChange(value)
            }}
            className="rounded-lg border-[1px] border-border custom-scroll"
        />
        <Dialog >
            <DialogTrigger asChild>
                <Button className="absolute right-2 top-0 size-5" size="medium" variant="text" color="default" iconOnly><Outlined.FullScreen size={14} /></Button>
            </DialogTrigger>
            <DialogContent className="h-[600px] max-h-[90vh] grid-rows-[auto_minmax(0,1fr)] lg:max-w-[800px]">
                <DialogHeader>
                    <DialogTitle className="flex items-center">
                        Code
                    </DialogTitle>
                </DialogHeader>
                <AceEditor
                    width="100%"
                    height="100%"
                    value={code}
                    mode="python"
                    highlightActiveLine={true}
                    showPrintMargin={false}
                    fontSize={14}
                    showGutter
                    enableLiveAutocompletion
                    theme={dark ? "twilight" : "github"}
                    name="CodeEditor"
                    onChange={(value) => {
                        setCode(value);
                        onChange(value)
                    }}
                    className="min-w-0 rounded-lg border-[1px] border-border custom-scroll"
                />
            </DialogContent>
        </Dialog>
    </div>
};
