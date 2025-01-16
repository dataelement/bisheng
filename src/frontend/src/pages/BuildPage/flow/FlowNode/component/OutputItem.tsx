import { Badge } from "@/components/bs-ui/badge";
import { Label } from "@/components/bs-ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next"; // 引入国际化
import { CustomHandle } from "..";
import DragOptions from "./DragOptions";
import VarInput from "./VarInput";

const OutputItem = ({ nodeId, node, data, onChange, onValidate }) => {
    const { t } = useTranslation('flow'); // 使用国际化
    const [interactionType, setInteractionType] = useState<string>(data.value.type || "none"); // 交互类型状态
    const options = useMemo(() => {
        return data.options.map(el => ({
            id: el.id,
            text: el.label,
            type: ''
        }))
    }, [data.options]);

    // 根据交互类型切换不同的展示
    const renderContent = () => {
        switch (interactionType) {
            case "none":
                return null;
            case "choose":
                return (
                    <DragOptions
                        edit
                        edges
                        options={options}
                        onChange={(opts) => {
                            data.options = opts.map(el => ({
                                id: el.id,
                                label: el.text,
                                value: ''
                            }));
                        }}
                    />
                );
            case "input":
                return (
                    <div className="node-item mb-2" data-key={data.key}>
                        <div className="flex justify-between items-center">
                            <Label className="bisheng-label">
                                {t("userInputLabel")} {/* 用户输入框展示内容 */}
                            </Label>
                            <Badge
                                variant="outline"
                                className="bg-[#E6ECF6] text-[#2B53A0]"
                            >
                                {data.key}
                            </Badge>
                        </div>
                        <VarInput
                            placeholder={t("userInputPlaceholder")}
                            nodeId={nodeId}
                            itemKey={data.key}
                            flowNode={data}
                            value={data.value.value}
                            onChange={(msg) =>
                                onChange({ type: interactionType, value: msg })
                            }
                        />
                    </div>
                );
            default:
                return null;
        }
    };

    const handleChangeType = (val) => {
        setInteractionType(val);
        if (interactionType === "choose" || val === "choose") {
            const addNodeEvent = new CustomEvent("outputDelEdge", {
                detail: { nodeId }
            });
            window.dispatchEvent(addNodeEvent);
        }
    }

    const [error, setError] = useState(false);
    useEffect(() => {
        data.required &&
            onValidate(() => {
                if (interactionType === "choose" && !data.options.length) {
                    setError(true);
                    return t("optionsCannotBeEmpty"); // 选项不可为空
                }
                setError(false);
                return false;
            });

        return () => onValidate(() => { });
    }, [data.value, interactionType]);

    return (
        <div className="node-item mb-4" data-key={data.key}>
            <Label className="bisheng-label">{data.label}</Label>
            {/* 交互类型选择器 */}
            <RadioGroup
                value={interactionType}
                onValueChange={(val) => {
                    handleChangeType(val)
                    onChange({ type: val, value: "" });
                    setError(false);
                }}
                className="mt-2"
            >
                <div className="flex items-center space-x-2">
                    <RadioGroupItem value="none" id="r1" />
                    <Label htmlFor="r1">{t("noInteraction")}</Label> {/* 无交互 */}
                </div>
                <div className="flex items-center space-x-2">
                    <RadioGroupItem value="choose" id="r2" />
                    <Label htmlFor="r2" className="flex items-center">
                        {t("chooseInteraction")} {/* 选择型交互 */}
                        <QuestionTooltip content={t("chooseInteractionTooltip")} />
                    </Label>
                </div>
                <div className="flex items-center space-x-2">
                    <RadioGroupItem value="input" id="r3" />
                    <Label htmlFor="r3" className="flex items-center">
                        {t("inputInteraction")} {/* 输入型交互 */}
                        <QuestionTooltip content={t("inputInteractionTooltip")} />
                    </Label>
                </div>
            </RadioGroup>

            <div className="interaction-content mt-4 nodrag">
                {renderContent()}
                {error && (
                    <div className="text-red-500 text-sm mt-2">
                        {t("optionsCannotBeEmpty")} {/* 选项不可为空 */}
                    </div>
                )}
                {interactionType !== "choose" && <CustomHandle node={node} />}
            </div>
        </div>
    );
};

export default OutputItem;
