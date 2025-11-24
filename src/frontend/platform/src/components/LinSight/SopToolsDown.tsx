import { ChevronRightIcon } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "../bs-ui/tooltip";

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
    const [isHoveringMenu, setIsHoveringMenu] = useState(false);

    // Initialize the state
    useEffect(() => {
        if (!open) {
            setHoverIndex(null);
            return;
        }

        // Find the active menu item based on the current value
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

    // Position adjustment logic
    useLayoutEffect(() => {
        if (!open || !popupRef.current) return;
        const SAFE_MARGIN = 8;

        const popup = popupRef.current;
        const popupRect = popup.getBoundingClientRect();

        // Get the boundaries of the parent container (default to viewport)
        const parentRect = parentRef?.current?.getBoundingClientRect() || {
            top: 0,
            left: 0,
            right: window.innerWidth,
            bottom: window.innerHeight,
            width: window.innerWidth,
            height: window.innerHeight
        };

        // Calculate the adjusted position (considering the parent's offset)
        let adjustedTop = position.top;
        let adjustedLeft = position.left;

        if (position.top + popupRect.height > parentRect.height) {
            adjustedTop = parentRect.height - popupRect.height - SAFE_MARGIN;
        }

        if (position.left + popupRect.width * 2 > parentRect.width) {
            adjustedLeft = parentRect.width - popupRect.width * 2 - SAFE_MARGIN;
        }

        setAdjustedPosition({ top: adjustedTop, left: adjustedLeft });
    }, [open, position, parentRef]);

    // Handle menu interaction
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

    // Close the menu if clicking outside
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
    {/* Dropdown popup */ }
    return <div
        ref={popupRef}
        className="absolute bg-white shadow-lg rounded-md border border-gray-200"
        style={{
            top: adjustedPosition.top,
            left: adjustedPosition.left,
            transform: 'translateZ(0)' // Ensure accurate rendering
        }}
        onClick={(e) => e.stopPropagation()}
    >
        <div className="flex text-sm">
            {/* First-level menu */}
            <div className="w-48 border-r border-gray-100 overflow-auto max-h-96">
                {options.map((option, index) => {
                    const hasChildren = option.children && option.children.length > 0;
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

            {/* Second-level menu */}
            {hoverIndex !== null && options[hoverIndex]?.children?.length > 0 && (
                <div className="w-44 max-h-96 overflow-y-auto">
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
                                        <p>{child.desc}</p>
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
}
