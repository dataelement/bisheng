import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/bs-ui/dialog";
import { darkContext } from "@/contexts/darkContext";
import { Expand } from "lucide-react";
import { useContext, useState } from "react";
import AceEditor from "react-ace";

export default function CodePythonItem({ data, onChange }) {
    const { dark } = useContext(darkContext);
    const [code, setCode] = useState(data.value);

    return <div className="relative">
        <AceEditor
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
            className="h-40 w-full rounded-lg border-[1px] border-border custom-scroll"
        />
        <Dialog >
            <DialogTrigger asChild>
                <Button className="absolute right-2 top-0 size-5" size="icon" variant="ghost"><Expand size={14} /></Button>
            </DialogTrigger>
            <DialogContent className="h-[600px] lg:max-w-[800px] ">
                <DialogHeader>
                    <DialogTitle className="flex items-center">
                        代码
                    </DialogTitle>
                </DialogHeader>
                <AceEditor
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
                    className="h-98 w-full rounded-lg border-[1px] border-border custom-scroll"
                />
            </DialogContent>
        </Dialog>
    </div>
};
