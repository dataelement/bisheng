import { Label } from "@/components/bs-ui/label";
import { Slider } from "@/components/bs-ui/slider";
import { Switch } from "@/components/bs-ui/switch";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import ModelItem from "./ModelItem";

interface InputPredictionConfigValues {
    model_id: string;
    predict_count: number;
    history_count: number;
    temperature: number;
    open: boolean;
}

interface InputPredictionConfigErrors {
    model_id?: boolean;
    temperature?: boolean;
}

interface InputPredictionConfigData {
    key: string;
    label: string;
    value: InputPredictionConfigValues;
    required?: boolean;
    help?: string;
}

interface InputPredictionConfigItemProps {
    data: InputPredictionConfigData;
    onChange: (value: InputPredictionConfigValues) => void;
    onValidate: (validateFn: () => string | false) => void;
}

export default function InputPredictionConfigItem({ data, onChange, onValidate }: InputPredictionConfigItemProps) {
    const { t } = useTranslation('flow');
    const [values, setValues] = useState<InputPredictionConfigValues>(data.value);
    const [errors, setErrors] = useState<InputPredictionConfigErrors>({});

    const { model_id, predict_count, history_count, temperature, open } = values;

    // 校验方法
    const handleValidate = () => {
        if (!open) return; // 开关关闭时无需校验

        const newErrors: InputPredictionConfigErrors = {};
        const errorMessages: string[] = [];

        if (!model_id) {
            newErrors.model_id = true;
            errorMessages.push(t("modelRequired")); // 模型不可为空
        }

        setErrors(newErrors);
        return errorMessages.length > 0 ? errorMessages[0] : false;
    };

    // 提供校验回调
    useEffect(() => {
        onValidate(handleValidate);
        return () => onValidate(() => { });
    }, [values, data.required]);

    const handleChange = (key: keyof InputPredictionConfigValues, value: any) => {
        const newValues = { ...values, [key]: value };
        setValues(newValues);
        setErrors((prev) => ({ ...prev, [key]: false })); // 清除错误状态
        onChange(newValues);
    };

    const handleModelValidate = (validateFn: () => string | false) => {
        // 为 ModelItem 提供校验回调
        return () => false; // 目前不需要额外的模型校验
    };

    return (
        <div className="node-item mb-4 relative" data-key={data.key}>
            <div className="flex justify-between items-center mb-2">
                <Label className="flex items-center bisheng-label">
                    {data.label}
                    {data.help && <QuestionTooltip content={data.help} />}
                </Label>
                {/* 开关 */}
                <Switch
                    checked={open}
                    onCheckedChange={(checked) => handleChange("open", checked)}
                />
            </div>

            {/* 配置表单 */}
            {open && (
                <div className="space-y-6">
                    {/* 模型配置组 */}
                    <div className="space-y-4">
                        <h4 className="text-sm font-medium text-gray-700 border-b pb-2">
                            {t("modelSettings")}
                        </h4>
                        
                        {/* 模型选择 */}
                        <div>
                            <ModelItem
                                data={{
                                    key: "model_id",
                                    label: t("model"),
                                    placeholder: t("selectModel"),
                                    value: model_id,
                                    required: true
                                }}
                                onChange={(value) => handleChange("model_id", value)}
                                onValidate={handleModelValidate}
                            />
                            {errors.model_id && (
                                <p className="text-red-500 text-sm mt-1">{t("modelRequired")}</p>
                            )}
                        </div>

                        {/* 温度设置 */}
                        <div>
                            <Label className="flex items-center bisheng-label mb-2">
                                {t("temperature")}
                            </Label>
                            <div className="flex gap-4">
                                <Slider
                                    value={[temperature]}
                                    min={0}
                                    max={2}
                                    step={0.1}
                                    onValueChange={(v) => handleChange("temperature", v[0])}
                                    className="flex-1"
                                />
                                <span className="w-12 text-center">{temperature.toFixed(1)}</span>
                            </div>
                        </div>
                    </div>

                    {/* 预测配置组 */}
                    <div className="space-y-4">
                        <h4 className="text-sm font-medium text-gray-700 border-b pb-2">
                            {t("predictionSettings")}
                        </h4>
                        
                        {/* 预测问题数量 */}
                        <div>
                            <Label className="flex items-center bisheng-label mb-2">
                                {t("predictCount")}
                            </Label>
                            <div className="flex gap-4">
                                <Slider
                                    value={[predict_count]}
                                    min={1}
                                    max={4}
                                    step={1}
                                    onValueChange={(v) => handleChange("predict_count", v[0])}
                                    className="flex-1"
                                />
                                <span className="w-8 text-center">{predict_count}</span>
                            </div>
                        </div>

                        {/* 历史消息数量 */}
                        <div>
                            <Label className="flex items-center bisheng-label mb-2">
                                {t("historyCount")}
                            </Label>
                            <div className="flex gap-4">
                                <Slider
                                    value={[history_count]}
                                    min={1}
                                    max={50}
                                    step={1}
                                    onValueChange={(v) => handleChange("history_count", v[0])}
                                    className="flex-1"
                                />
                                <span className="w-8 text-center">{history_count}</span>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
} 