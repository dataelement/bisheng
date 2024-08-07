import { Button } from "@/components/bs-ui/button";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { getEvaluationModelConfig, updateEvaluationModelConfig } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useEffect, useState } from "react";

export default function EvaluationModel({ llmOptions, onBack }) {
    const [selectedModel, setSelectedModel] = useState(null);
    useEffect(() => {
        getEvaluationModelConfig().then(res => setSelectedModel(res.model_id))
    }, []);

    const { message } = useToast()
    const handleSave = () => {
        const data = {
            model_id: selectedModel
        };
        captureAndAlertRequestErrorHoc(updateEvaluationModelConfig(data).then(res => {
            message({ variant: 'success', description: '保存成功' })
        }));
    };

    return (
        <div className="max-w-[520px] mx-auto">
            <div className="mt-10">
                <span>评测功能默认模型</span>
                <Select value={selectedModel} onValueChange={(val) => setSelectedModel(val)}>
                    <SelectTrigger className="mt-2">
                        <SelectValue placeholder="选择模型" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectGroup>
                            {llmOptions.map((option) => (
                                <SelectItem key={option.id} value={option.id}>{option.model_name}</SelectItem>
                            ))}
                        </SelectGroup>
                    </SelectContent>
                </Select>
            </div>
            <div className="mt-10 text-center space-x-6">
                <Button variant="outline" onClick={onBack}>取消</Button>
                <Button onClick={handleSave}>保存</Button>
            </div>
        </div>
    );
}
