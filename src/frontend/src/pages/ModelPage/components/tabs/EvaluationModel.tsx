import { Button } from "@/components/bs-ui/button";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";

export default function EvaluationModel({ onBack }) {
    return <div>
        <div className="mt-10">
            <span>评测功能默认模型</span>
            <Select>
                <SelectTrigger className="mt-2">
                    <SelectValue placeholder=""/>
                </SelectTrigger>
                <SelectContent>
                    <SelectGroup>
                        {/* <SelectItem></SelectItem> */}
                    </SelectGroup>
                </SelectContent>
            </Select>
        </div>
        <div className="mt-10 text-center space-x-6">
            <Button variant="outline" onClick={() => onBack()}>取消</Button>
            <Button>保存</Button>
        </div>
    </div>
}