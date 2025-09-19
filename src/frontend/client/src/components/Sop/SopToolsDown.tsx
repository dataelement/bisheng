import { ChevronRightIcon } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import ReactDOM from "react-dom";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip2";

export default function SopToolsDown({
    open,
    position = { top: 0, left: 0 },
    value,
    options,
    onChange,
    onClose,
    parentRef
}: {
    open: boolean;
    position?: { top: number; left: number };
    value?: string;
    options: {
        label: string;
        value?: string;
        desc: string;
        children?: {
            label: string;
            value: string;
            desc: string;
        }[];
    }[];
    onChange: (value: any) => void;
    onClose: () => void;
    parentRef?: React.RefObject<HTMLElement>;
}) {
    const [hoverIndex, setHoverIndex] = useState<number | null>(null);
    const [adjustedPosition, setAdjustedPosition] = useState(position);
    const popupRef = useRef<HTMLDivElement>(null);

    // 初始化状态
    useEffect(() => {
        if (!open) {
            setHoverIndex(null);
            return;
        }

        // 根据当前值查找激活的菜单项
        let foundActiveIndex: any = null;
        options.forEach((option, index) => {
            if (option.value === value) foundActiveIndex = index;
            if (option.children) {
                option.children.forEach(child => {
                    if (child.value === value) foundActiveIndex = index;
                });
            }
        });

        setHoverIndex(foundActiveIndex);
    }, [open, value, options]);

    // 精确位置调整逻辑
    useLayoutEffect(() => {
        if (!open || !popupRef.current) return;

        const popup = popupRef.current;
        const popupRect = popup.getBoundingClientRect();

        // 获取父容器边界（默认为视口）
        const parentRect = parentRef?.current?.getBoundingClientRect() || {
            top: 0,
            left: 0,
            right: window.innerWidth,
            bottom: window.innerHeight,
            width: window.innerWidth,
            height: window.innerHeight
        };

        // 计算修正后的位置（考虑父元素偏移）
        let adjustedTop = position.top;
        let adjustedLeft = position.left;

        // 1. 右侧超出 - 向左调整
        if (adjustedLeft + popupRect.width > parentRect.right) {
            adjustedLeft = parentRect.right - popupRect.width;
        }

        // 2. 底部超出 - 向上调整
        if (adjustedTop + popupRect.height > parentRect.bottom) {
            adjustedTop = parentRect.bottom - popupRect.height;
        }

        // 3. 左侧超出 - 向右调整
        if (adjustedLeft < parentRect.left) {
            adjustedLeft = parentRect.left;
        }

        // 4. 顶部超出 - 向下调整
        if (adjustedTop < parentRect.top) {
            adjustedTop = parentRect.top;
        }

        // 5. 添加安全边距（确保不贴边）
        const SAFE_MARGIN = 5;
        adjustedTop = Math.max(parentRect.top + SAFE_MARGIN, Math.min(adjustedTop, parentRect.bottom - popupRect.height - SAFE_MARGIN));
        adjustedLeft = Math.max(parentRect.left + SAFE_MARGIN, Math.min(adjustedLeft, parentRect.right - popupRect.width - SAFE_MARGIN));

        setAdjustedPosition({ top: adjustedTop, left: adjustedLeft });
    }, [open, position, parentRef]);

    // 处理菜单交互
    const handleParentHover = (index: number) => setHoverIndex(index);

    const handleParentClick = (index: number, e: React.MouseEvent) => {
        e.stopPropagation();
        const option = options[index];

        if (!option.children?.length && option.value) {
            onChange(option);
            onClose();
            return;
        }

    };

    const handleChildClick = (obj: any, e: React.MouseEvent) => {
        e.stopPropagation();
        onChange(obj);
        onClose();
    };

    // 阻止背景滚动
    useEffect(() => {
        if (open) {
            document.body.style.overflow = 'hidden';
            return () => {
                document.body.style.overflow = '';
            };
        }
    }, [open]);

    if (!open) return null;

    return ReactDOM.createPortal(
        <>
            {/* 半透明蒙层 */}
            <div
                className="fixed inset-0 z-10"
                onClick={onClose}
            />

            {/* 下拉弹窗 */}
            <div
                ref={popupRef}
                className="fixed z-10 bg-white shadow-lg rounded-md border border-gray-200"
                style={{
                    top: adjustedPosition.top,
                    left: adjustedPosition.left,
                    transform: 'translateZ(0)' // 确保精确渲染
                }}
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex text-sm">
                    {/* 一级菜单 */}
                    <div className="w-48 border-r border-gray-100 overflow-auto max-h-96">
                        {options.map((option, index) => {
                            const hasChildren = option.children && option.children.length > 0;
                            const isHovered = hoverIndex === index;

                            return (
                                <div
                                    key={option.label}
                                    className={`
                                        relative flex items-center justify-between px-3 py-2 cursor-pointer
                                        transition-colors
                                        ${isHovered ? "bg-blue-50 font-medium" : ""}
                                    `}
                                    onMouseEnter={() => handleParentHover(index)}
                                    onClick={(e) => handleParentClick(index, e)}
                                >
                                    {option.desc ? (
                                        <Tooltip disableHoverableContent>
                                            <TooltipTrigger asChild>
                                                <div className="truncate">{option.label}</div>
                                            </TooltipTrigger>
                                            <TooltipContent>
                                                <p>{option.desc}</p>
                                            </TooltipContent>
                                        </Tooltip>
                                    ) : (
                                        <div className="truncate">{option.label}</div>
                                    )}
                                    {hasChildren && (
                                        <ChevronRightIcon className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                                    )}
                                </div>
                            );
                        })}
                    </div>

                    {/* 二级菜单 */}
                    {hoverIndex !== null && options[hoverIndex]?.children?.length > 0 && (
                        <div className="w-[178px] max-h-96 overflow-y-auto">
                            {options[hoverIndex].children?.map((child, childIndex) => (
                                <div
                                    key={childIndex}
                                    className="px-3 py-2 cursor-pointer transition-colors hover:bg-blue-50"
                                    onClick={(e) => handleChildClick(child, e)}
                                >
                                    {child.desc ? (
                                        <Tooltip disableHoverableContent>
                                            <TooltipTrigger asChild>
                                                <div className="truncate">{child.label}</div>
                                            </TooltipTrigger>
                                            <TooltipContent>
                                                <p className="break-all max-w-96">{child.desc}</p>
                                            </TooltipContent>
                                        </Tooltip>
                                    ) : (
                                        <div className="truncate">{child.label}</div>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </>,
        document.body
    );
}