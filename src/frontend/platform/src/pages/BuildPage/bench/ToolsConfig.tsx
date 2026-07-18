// src/pages/BuildPage/bench/ToolsConfig.tsx
//
// v2.5 Agent 模式「可用工具」配置面板。
// 数据模型与灵思 linsight_config.tools 保持一致：顶层是工具父分组，
// children[] 存放选中的子工具；daily 模式在父级新增 default_checked，
// 控制工作台输入区的默认开启状态。后端根据 children[].id 调度具体工具。
import ToolSelectorContainer from "@/components/LinSight/ToolSelectorContainer";
import { Label } from "@/components/bs-ui/label";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { getToolsApi } from "@/controllers/API/tools";
import { cloneDeep } from "lodash-es";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

export interface ToolChildConfig {
    id: number;
    name: string;
    tool_key: string;
    desc?: string;
}

export interface ToolConfig {
    id: number;
    name: string;
    is_preset?: number;
    description?: string;
    default_checked: boolean;
    children: ToolChildConfig[];
}

const MAX_TOOLS = 20;

type ToolCategory = "builtin" | "api" | "mcp";

interface Props {
    tools: ToolConfig[];
    onChange: (next: ToolConfig[]) => void;
}

export default function ToolsConfig({ tools, onChange }: Props) {
    const { t } = useTranslation();
    const { toast } = useToast();
    const [activeToolTab, setActiveToolTab] = useState<ToolCategory>("builtin");
    const [toolSearchTerm, setToolSearchTerm] = useState("");
    const [showToolSelector, setShowToolSelector] = useState(true);
    const [toolsData, setToolsData] = useState<Record<ToolCategory, any[]>>({
        builtin: [],
        api: [],
        mcp: [],
    });

    const fetchTools = async (category: ToolCategory) => {
        if (toolsData[category].length) return;
        try {
            const bucket = category === "builtin" ? "default" : category === "api" ? "custom" : "mcp";
            const res: any = await getToolsApi(bucket);
            setToolsData((prev) => ({ ...prev, [category]: res || [] }));
        } catch {
            toast({ variant: "error", description: t("bench.fetchToolsFailed", { type: category }) });
        }
    };

    useEffect(() => {
        fetchTools(activeToolTab);
    }, [activeToolTab]);

    // Parent-group limit — the toast fires on attempts to add a 21st parent or
    // to add a child whose parent wasn't in the selected set yet once at cap.
    const atCapacityForNewParent = (parentId: number) =>
        tools.length >= MAX_TOOLS && !tools.some((t) => t.id === parentId);

    const toggleTool = useCallback(
        (parent: any, child: any) => {
            const parentIndex = tools.findIndex((t) => t.id === parent.id);
            if (parentIndex > -1) {
                const existingParent = tools[parentIndex];
                const childIndex = existingParent.children.findIndex((c) => c.id === child.id);
                const nextChildren = childIndex === -1
                    ? [...existingParent.children, {
                        id: child.id,
                        name: child.name,
                        tool_key: child.tool_key,
                        desc: child.desc,
                    }]
                    : existingParent.children.filter((_, i) => i !== childIndex);
                if (nextChildren.length === 0) {
                    onChange(tools.filter((t) => t.id !== parent.id));
                    return;
                }
                const next = [...tools];
                next[parentIndex] = { ...existingParent, children: nextChildren };
                onChange(next);
                return;
            }
            if (atCapacityForNewParent(parent.id)) {
                toast({
                    variant: "warning",
                    description: t("bench.toolLimitReached", { max: MAX_TOOLS }),
                });
                return;
            }
            onChange([
                ...tools,
                {
                    id: parent.id,
                    name: parent.name,
                    is_preset: parent.is_preset,
                    description: parent.description,
                    default_checked: false,
                    children: [{
                        id: child.id,
                        name: child.name,
                        tool_key: child.tool_key,
                        desc: child.desc,
                    }],
                },
            ]);
        },
        [tools, onChange, t, toast],
    );

    const toggleGroup = useCallback(
        (group: any, checked: boolean) => {
            if (!checked) {
                onChange(tools.filter((t) => t.id !== group.id));
                return;
            }
            if (atCapacityForNewParent(group.id)) {
                toast({
                    variant: "warning",
                    description: t("bench.toolLimitReached", { max: MAX_TOOLS }),
                });
                return;
            }
            const existing = tools.find((t) => t.id === group.id);
            const cloned = cloneDeep(group);
            const next: ToolConfig = {
                id: group.id,
                name: group.name,
                is_preset: group.is_preset,
                description: group.description,
                default_checked: existing?.default_checked ?? false,
                children: (cloned.children || []).map((c: any) => ({
                    id: c.id,
                    name: c.name,
                    tool_key: c.tool_key,
                    desc: c.desc,
                })),
            };
            onChange([...tools.filter((t) => t.id !== group.id), next]);
        },
        [tools, onChange, t, toast],
    );

    const isToolSelected = useCallback(
        (toolId: number, childId: number) => {
            const parent = tools.find((t) => t.id === toolId);
            return !!parent?.children.some((c) => c.id === childId);
        },
        [tools],
    );

    const removeTool = useCallback(
        (index: number) => {
            const next = [...tools];
            next.splice(index, 1);
            onChange(next);
        },
        [tools, onChange],
    );

    const handleDragEnd = useCallback(
        (result: any) => {
            if (!result.destination) return;
            if (result.destination.index === result.source.index) return;
            const next = [...tools];
            const [moved] = next.splice(result.source.index, 1);
            next.splice(result.destination.index, 0, moved);
            onChange(next);
        },
        [tools, onChange],
    );

    const handleDefaultCheckedChange = useCallback(
        (toolId: number, defaultChecked: boolean) => {
            onChange(tools.map((t) => (t.id === toolId ? { ...t, default_checked: defaultChecked } : t)));
        },
        [tools, onChange],
    );

    return (
        <div className="mb-6">
            <Label className="text-lg font-bold flex items-center">
                {t("bench.availableTools")}
            </Label>
            <div className="mt-2">
                <ToolSelectorContainer
                    toolsData={toolsData}
                    selectedTools={tools}
                    toggleTool={toggleTool}
                    removeTool={removeTool}
                    isToolSelected={isToolSelected}
                    handleDragEnd={handleDragEnd}
                    toggleGroup={toggleGroup}
                    activeToolTab={activeToolTab}
                    setActiveToolTab={setActiveToolTab}
                    showToolSelector={showToolSelector}
                    setShowToolSelector={setShowToolSelector}
                    toolSearchTerm={toolSearchTerm}
                    setToolSearchTerm={setToolSearchTerm}
                    showDefaultChecked
                    onDefaultCheckedChange={handleDefaultCheckedChange}
                    defaultCheckedLabel={t("bench.defaultChecked")}
                />
            </div>
        </div>
    );
}
