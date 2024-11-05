import { Button } from "@/components/bs-ui/button";
import Tip from "@/components/bs-ui/tooltip/tip";
import { Copy, Play, Trash2 } from "lucide-react";

export default function NodeToolbarComponent({ nodeId, type }) {

    const handleDelete = () => {
        const event = new CustomEvent('nodeDelete', {
            detail: nodeId
        });
        window.dispatchEvent(event);
    }

    const handleCopy = () => {
        const event = new CustomEvent('nodeCopy', {
            detail: [nodeId]
        });
        window.dispatchEvent(event);
    }

    return <div className="rounded-xl shadow-sm p-1 bg-gradient-to-r from-gray-50 to-[#fff] border">
        <Tip content="运行此节点" side="top">
            <Button size="icon" variant="ghost" className="size-8" disabled><Play size={16} /></Button>
        </Tip>
        <Tip content="复制" side="top">
            <Button
                size="icon"
                variant="ghost"
                className={`size-8 ${type === 'start' ? 'hidden' : ''}`}
                onClick={handleCopy}
            >
                <Copy size={16} />
            </Button>
        </Tip>
        <Tip content="删除" side="top">
            <Button
                size="icon"
                variant="ghost"
                className={`size-8 hover:text-red-600 ${type === 'start' ? 'hidden' : ''}`}
                onClick={handleDelete}
            >
                <Trash2 size={16} />
            </Button>
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
