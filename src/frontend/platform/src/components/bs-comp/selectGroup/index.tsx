import { SearchInput } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectTrigger } from "@/components/bs-ui/select";
import { cname } from "@/components/bs-ui/utils";
import { generateUUID } from "@/utils";
import { ChevronRight, X } from "lucide-react";
import { useRef, useState } from "react";


const SelectGroup = ({ 
    value,
    disabled,
    onChange,
    options,
    className = '',
    contentClassName = '',
    showSearch = false,
    id = `${Date.now()}`,
    searchPlaceholder = '',
    handleSearch = (e) => {}
}
) => {
    const [open, setOpen] = useState(false);
    const [expandedNodes, setExpandedNodes] = useState(new Set());
    const inputRef = useRef(null)
    const idRef = useRef(generateUUID(4))

    // 将一维数组转换为树形结构
    const buildTree = (nodes) => {
        const map = new Map();
        const roots = [];

        nodes.forEach((node) => {
            map.set(node.id, { ...node, children: [] });
        });

        nodes.forEach((node) => {
            if (node.pid === null) {
                roots.push(map.get(node.id));
            } else {
                const parent = map.get(node.pid);
                if (parent) {
                    parent.children.push(map.get(node.id));
                }
            }
        });

        return roots;
    };

    // 递归渲染树形结构
    const renderTree = (nodes, level = 0) => {
        return nodes.map((node) => {
            const isExpanded = expandedNodes.has(node.id); // 判断是否展开
            const isSelected = value?.id === node.id; // 判断是否选中

            return (
                <div key={node.id} className="pl-2">
                    <div
                        className={`flex items-center gap-2 cursor-pointer ${isSelected ? 'bg-blue-200' : ''} hover:bg-blue-100 rounded-md p-1`}
                        onClick={() => {
                            onChange({ id: node.id, group_name: node.group_name });
                            setOpen(false);
                        }}
                    >
                        {node.children?.length > 0 && (
                            <ChevronRight
                                size={18}
                                className={`cursor-pointer ${isExpanded ? 'rotate-90' : ''}`}
                                onClick={(e) => {
                                    e.stopPropagation(); // 阻止事件冒泡
                                    setExpandedNodes((prev) =>
                                        isExpanded ? new Set([...prev].filter((id) => id !== node.id)) : new Set([...prev, node.id])
                                    );
                                }}
                            />
                        )}
                        <Label>{node.group_name}</Label>
                    </div>
                    {/* 递归渲染子节点 */}
                    {isExpanded && node.children && (
                        <div className="pl-4">{renderTree(node.children, level + 1)}</div>
                    )}
                </div>
            );
        });
    };

    // const treeData = buildTree(options);
    console.log('options :>> ', options, value);
    return <Select open={open} onOpenChange={setOpen}>
        <SelectTrigger className={cname(`group min-h-9 py-1 ${scroll ? 'h-9 overflow-y-auto items-start pt-1.5' : 'h-auto'}`, className)} disabled={disabled}>
            <div className="text-foreground inline-flex flex-1 flex-row justify-between items-center overflow-hidden">
                <div className={`${value?.group_name} text-gray-600`}>{value?.group_name || '用户组'}</div>
                {value && <X
                    className="
                        h-3.5 w-3.5 min-w-3.5 
                        opacity-0 group-hover:opacity-100
                        transition-opacity duration-200
                        bg-black rounded-full
                        flex items-center justify-center
                        flex-shrink-0
                    "
                    color="#ffffff"
                    onPointerDown={(e) => e.stopPropagation()}
                    onClick={() => {
                        onChange(undefined);
                    }}
                />}
            </div>
        </SelectTrigger >
        <SelectContent
            id={idRef.current}
            // position="popper"
            className={contentClassName + ' overflow-visible'}
            avoidCollisions={false}
            headNode={
                <div className="p-2">
                    {showSearch && <SearchInput id={id} ref={inputRef} inputClassName="h-8 dark:border-gray-700" placeholder={searchPlaceholder} onChange={handleSearch} iconClassName="w-4 h-4" />}
                </div>
            }
        >
            <div >
                <div className="p-2">{renderTree(options)}</div>
            </div>
        </SelectContent>
    </Select >
};

export default SelectGroup;


