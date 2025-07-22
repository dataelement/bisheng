import { ChevronRightIcon } from "lucide-react";
import { useEffect, useState } from "react";

export default function SopToolsDown({
    open,
    position = { top: 0, left: 0 },
    value,
    options,
    onChange,
    onClose
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
}) {
    const [hoverIndex, setHoverIndex] = useState<number | null>(null);
    const [activeIndex, setActiveIndex] = useState<number | null>(null);
    const [isHoveringMenu, setIsHoveringMenu] = useState(false);

    // 初始化状态
    useEffect(() => {
        if (!open) {
            setHoverIndex(null);
            return;
        }

        // 根据当前值查找激活的菜单项
        let foundActiveIndex: any = null;
        options.forEach((option, index) => {
            // 检查一级菜单是否匹配
            if (option.value === value) {
                foundActiveIndex = index;
            }

            // 检查二级菜单是否匹配
            if (option.children) {
                option.children.forEach(child => {
                    if (child.value === value) {
                        foundActiveIndex = index;
                    }
                });
            }
        });

        setActiveIndex(foundActiveIndex);
        setHoverIndex(foundActiveIndex); // 初始显示选中项的子菜单
    }, [open, value, options]);

    // 处理一级菜单悬停
    const handleParentHover = (index: number) => {
        setHoverIndex(index);
    };

    // 处理一级菜单点击
    const handleParentClick = (index: number, e: React.MouseEvent) => {
        e.stopPropagation();
        const option = options[index];

        // 如果没有子菜单，直接选中并关闭菜单
        if (!option.children || option.children.length === 0) {
            if (option.value) {
                onChange(option);
                onClose();
            }
            return;
        }

        // 有子菜单时标记为激活状态
        setActiveIndex(index);
    };

    // 处理二级菜单点击
    const handleChildClick = (obj: any, e: React.MouseEvent) => {
        e.stopPropagation();
        onChange(obj);
        onClose();
    };

    // 点击外部关闭菜单
    useEffect(() => {
        if (!open) return;

        const handleClickOutside = () => {
            if (!isHoveringMenu) {
                onClose();
            }
        };

        document.addEventListener("click", handleClickOutside);
        return () => document.removeEventListener("click", handleClickOutside);
    }, [open, onClose, isHoveringMenu]);

    if (!open) return null;

    return (
        <div
            className="absolute z-[999] bg-[#fff] shadow-lg rounded-md border border-gray-200"
            style={{ top: position.top, left: position.left }}
            onClick={(e) => e.stopPropagation()}
            onMouseEnter={() => setIsHoveringMenu(true)}
            onMouseLeave={() => setIsHoveringMenu(false)}
        >
            <div className="flex text-sm">
                {/* 一级菜单 */}
                <div className="w-40 border-r border-gray-100">
                    {options.map((option, index) => {
                        const hasChildren = option.children && option.children.length > 0;
                        const isActive = activeIndex === index;
                        const isHovered = hoverIndex === index;

                        return (
                            <div
                                key={index}
                                className={`
                  relative flex items-center justify-between px-3 py-2 cursor-pointer
                  transition-colors
                  ${isHovered ? "bg-blue-50 font-medium" : ""}
                `}
                                onMouseEnter={() => handleParentHover(index)}
                                onClick={(e) => handleParentClick(index, e)}
                            >
                                {/* <TooltipAnchor
                                    side="top"
                                    description={option.desc}
                                    className="truncate"
                                    disabled={!option.desc}
                                > */}
                                <div className="truncate">{option.label}</div>
                                {/* </TooltipAnchor> */}
                                {hasChildren && (
                                    <ChevronRightIcon className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                                )}
                            </div>
                        );
                    })}
                </div>

                {/* 二级菜单 */}
                {hoverIndex !== null && options[hoverIndex]?.children?.length > 0 && (
                    <div className="w-40 max-h-96 overflow-y-auto">
                        {options[hoverIndex].children?.map((child, childIndex) => (
                            <div
                                key={childIndex}
                                className={`
                                    px-3 py-2 cursor-pointer transition-colors hover:bg-blue-50
                                    `}
                                onClick={(e) => handleChildClick(child, e)}
                            >
                                {/* <TooltipAnchor
                                    side="top"
                                    description={child.desc}
                                    className="truncate"
                                    disabled={!child.desc}
                                > */}
                                <div className="truncate">{child.label}</div>
                                {/* </TooltipAnchor> */}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}