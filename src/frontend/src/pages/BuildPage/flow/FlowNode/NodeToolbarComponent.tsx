import { Button } from "@/components/bs-ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/bs-ui/select";
import Tip from "@/components/bs-ui/tooltip/tip";
import { AlarmClock, CirclePlay, Copy, Download, Ellipsis, SaveAll, Settings2, Trash2 } from "lucide-react";

export default function NodeToolbarComponent(params) {

    return <div className="rounded-md shadow-sm px-2 bg-gradient-to-r from-gray-50 to-[#fff] border">
        <Tip content="运行此节点" side="top">
            <Button size="icon" variant="ghost"><CirclePlay className="size-4"/> </Button>
        </Tip>
        <Tip content="复制" side="top">
            <Button size="icon" variant="ghost"><Copy className="size-4" /> </Button>
        </Tip>
        <Tip content="删除" side="top">
            <Button size="icon" variant="ghost"><Trash2 className="size-4" /> </Button>
        </Tip>
        {/* <Select onValueChange={() => { }} value="">
            <SelectTrigger showIcon={false} className="border-none inline-flex w-9 h-9 p-0 shadow-none">
                <Button size="icon" variant="ghost"><Ellipsis /></Button>
            </SelectTrigger>
            <SelectContent>
                <SelectItem value={"export"}>
                    <div className="flex" data-testid="save-button-modal">
                        <Download className="relative top-0.5 mr-2 h-4 w-4" />
                        export
                    </div>
                </SelectItem>
                <SelectItem value={"saveCom"}>
                    <div className="flex" data-testid="save-button-modal">
                        <SaveAll className="relative top-0.5 mr-2 h-4 w-4" />
                        Save
                    </div>
                </SelectItem>
            </SelectContent>
        </Select> */}
    </div>
};
