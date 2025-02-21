import { Button } from "@/components/bs-ui/button";
import { Input, Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { Switch } from "@/components/bs-ui/switch";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { getChatAnalysisConfigApi, updateChatAnalysisConfigApi } from "@/controllers/API/log";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";

const defaultPrompt = `你是一名聊天记录内容审核专家。请审查下列按顺序编号的聊天记录，并检测每条消息中是否违规泄漏在以下有关客户的信息：
- 身份证号码
- 客户地址
- 姓名
- 性别
- 生日
- 电话号码
要求：
1. 对于每条消息，如果发现存在上述违规信息，则认为该消息存在违规。
2. 输出时只需返回违规消息的消息编号（以整数表示）以及违规情况；
3. 最终结果必须采用合法的 JSON 格式，形如：
\`\`\`json
{
  "messages": [
    {
      "message_id": 2,
      "violations": ["泄漏身份证号码、电话"]
    },
    {
      "message_id": 5,
      "violations": ["泄漏客户地址"]
    }
    // 如有其他违规消息，继续添加对应对象
  ]
}
\`\`\`
4. 如果检测到的聊天记录中没有任何违规消息，则输出：
\`\`\`json
{
  "messages": []
}
\`\`\`
请根据上述要求审查以下聊天记录并输出结果：`

export default function SessionAnalysisStrategy({ onBack }) {
    const { message, toast } = useToast();

    const [formData, setFormData] = useState({
        reviewEnabled: false,
        reviewKeywords: defaultPrompt,
        reviewFrequency: "weekly",  // default "weekly"
        reviewTime: "09:00",        // default time for weekly frequency
        reviewDay: "Monday",        // default day for weekly review
    });

    useEffect(() => {
        // On initial load, fetch the latest configuration and set it to formData
        getChatAnalysisConfigApi().then(config => {
            setFormData(config);
        });
    }, []);

    const handleSave = () => {
        if (!formData.reviewKeywords) {
            return message({
                variant: 'warning',
                description: '审查提示词不可为空',
            });
        }

        // Simulate saving the configuration (API call)
        captureAndAlertRequestErrorHoc(updateChatAnalysisConfigApi(formData).then(() => {
            toast({
                variant: 'success',
                description: '配置已生效',
            });
            onBack();  // Close the page after successful save
        }))
    };

    const handleCancel = () => {
        onBack();  // Close the page without saving
    };

    const handleSwitchChange = (val) => {
        setFormData(prev => ({ ...prev, reviewEnabled: val }));
    };

    const handleFrequencyChange = (val) => {
        setFormData(prev => ({
            ...prev,
            reviewFrequency: val,
            reviewTime: val === 'daily' ? '09:00' : prev.reviewTime,
            reviewDay: val === 'weekly' ? 'Mon' : prev.reviewDay,
        }));
    };

    return (
        <div className="relative size-full py-4">
            <div className="flex ml-6 items-center gap-x-3">
                <ShadTooltip content="返回" side="right">
                    <button className="extra-side-bar-buttons w-[36px]" onClick={onBack}>
                        <ArrowLeft strokeWidth={1.5} className="side-bar-button-size" />
                    </button>
                </ShadTooltip>
                <span>会话分析策略</span>
            </div>
            <div className="w-[50%] min-w-64 px-4 pb-10 mx-auto mt-6 h-[calc(100vh-220px)] overflow-y-auto">
                {/* 违规审查 */}
                <div className="mb-2">
                    <Label className="bisheng-label">违规审查
                        <QuestionTooltip className="relative top-0.5 ml-1" content="开启后系统将定期执行违规审查" />
                    </Label>
                    <div className="flex items-center gap-x-6 mt-1">
                        <Switch checked={formData.reviewEnabled} onCheckedChange={handleSwitchChange} />
                    </div>
                </div>
                {/* Show form fields only if reviewEnabled is true */}
                {formData.reviewEnabled && (
                    <>
                        {/* 审查提示词 */}
                        <div className="mb-2">
                            <Label className="bisheng-label">审查提示词</Label>
                            <Textarea
                                value={formData.reviewKeywords}
                                onChange={(e) => setFormData({ ...formData, reviewKeywords: e.target.value })}
                                className="min-h-80 mt-1"
                            />
                        </div>

                        {/* 审查频率 */}
                        <div className="mb-2">
                            <Label className="bisheng-label">审查频率
                                <QuestionTooltip className="relative top-0.5 ml-1" content="开启后系统将定期执行违规审查" />
                            </Label>
                            <div className="flex gap-x-4 mt-1">
                                <Select value={formData.reviewFrequency} onValueChange={handleFrequencyChange}>
                                    <SelectTrigger className="h-8 w-1/2">
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectGroup>
                                            <SelectItem value="daily">每天</SelectItem>
                                            <SelectItem value="weekly">每周</SelectItem>
                                        </SelectGroup>
                                    </SelectContent>
                                </Select>

                                {formData.reviewFrequency === 'weekly' && (
                                    <Select value={formData.reviewDay} onValueChange={(val) => setFormData({ ...formData, reviewDay: val })}>
                                        <SelectTrigger className="h-8 w-1/2">
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectGroup>
                                                <SelectItem value="Mon">周一</SelectItem>
                                                <SelectItem value="Tue">周二</SelectItem>
                                                <SelectItem value="Wed">周三</SelectItem>
                                                <SelectItem value="Thur">周四</SelectItem>
                                                <SelectItem value="Fri">周五</SelectItem>
                                                <SelectItem value="Sat">周六</SelectItem>
                                                <SelectItem value="Sun">周日</SelectItem>
                                            </SelectGroup>
                                        </SelectContent>
                                    </Select>
                                )}

                                {/* Time input for both "每天" and "每周" */}
                                <Input
                                    type="time"
                                    value={formData.reviewTime}
                                    onChange={(e) => setFormData({ ...formData, reviewTime: e.target.value })}
                                    className="w-1/2 h-8"
                                />
                            </div>
                        </div>
                    </>
                )}
                <div className="absolute right-0 bottom-0 p-4 flex gap-4">
                    <Button className="px-8" variant="outline" onClick={handleCancel}>取消</Button>
                    <Button className="px-16" onClick={handleSave}>保存</Button>
                </div>
            </div>
        </div >
    );
}
