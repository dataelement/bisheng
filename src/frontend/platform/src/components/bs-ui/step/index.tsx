import { Check } from "lucide-react";
import React from "react";
import { cname } from "../utils";
/**
 * 
组件参数说明：
 
    参数名	类型	默认值	说明
    steps	number	2	总步骤数
    currentStep	number	1	当前所在步骤（从1开始）
    align	string	"left"	对齐方式，可选值："left", "center", "right"
    labels	string[]	[]	自定义步骤文字，数组长度需与steps一致，未提供时显示"第 x 步"
 */
interface StepProgressProps {
    steps?: number;
    currentStep?: number;
    align?: "left" | "center" | "right";
    labels?: string[];
    className?: string;
}

/**
使用示例：
    // 三步流程，当前在第二步，居中布局
    <StepProgress
        steps={3}
        currentStep={2}
        align="center"
        labels={["填写信息", "验证身份", "完成注册"]}
    />
*/
export default function StepProgress({
    steps = 2,
    currentStep = 1,
    align = "left",
    labels = [],
    className = ""
}: StepProgressProps) {
    steps = labels.length || steps;
    // 处理边界情况
    const validatedStep = Math.min(Math.max(currentStep, 1), steps);
    const alignmentClasses = {
        left: "justify-start",
        center: "justify-center",
        right: "justify-end"
    };

    return (
        <div className={cname("flex items-center gap-4 text-sm font-medium", alignmentClasses[align], className)}>
            {Array.from({ length: steps }).map((_, index) => {
                const isCompleted = index < validatedStep - 1;
                const isCurrent = index === validatedStep - 1;

                return (
                    <React.Fragment key={index}>
                        <div className="flex items-center gap-2">
                            {/* 圆形指示器 */}
                            <div
                                className={cname(
                                    "flex size-6 items-center justify-center rounded-full text-xs font-semibold text-white transition-colors",
                                    isCompleted || isCurrent ? "bg-primary" : "bg-primary/35"
                                )}
                            >
                                {isCompleted ? <Check size={14} /> : <span>{index + 1}</span>}
                            </div>
                            {/* 步骤文字 */}
                            <span
                                className={cname(
                                    "whitespace-nowrap text-sm transition-colors",
                                    isCompleted || isCurrent ? "text-primary" : "text-gray-500"
                                )}
                            >
                                {labels[index] || `第 ${index + 1} 步`}
                            </span>
                        </div>
                        {/* 步骤连接线 */}
                        {index !== steps - 1 && (
                            <div
                                className={cname(
                                    "h-px w-8 transition-colors md:w-12",
                                    isCompleted ? "bg-primary" : "bg-gray-300"
                                )}
                            />
                        )}
                    </React.Fragment>
                );
            })}
        </div>
    );
}
