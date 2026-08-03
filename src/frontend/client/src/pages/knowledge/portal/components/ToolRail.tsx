import { BriefcaseBusiness, Clock, FileText, Link2, Lock, PanelRight } from "lucide-react";
import type { PanelKey, PortalToolRailKey } from "../types";
import s from "../PortalKnowledgeWorkbench.module.css";

const AI_ASSISTANT_ICON_SRC = `${__APP_ENV__.BASE_URL}/assets/channel/ai-assistant.png`;

const TOOLBAR_ITEMS: Array<{
    key: PortalToolRailKey;
    title: string;
    /** Absent for the AI entry, which renders the assistant avatar image instead. */
    icon?: typeof PanelRight;
    panelKey?: Extract<PanelKey, "properties" | "time" | "source" | "usage" | "permission">;
}> = [
        { key: "toggle", title: "侧边栏展开和关闭", icon: PanelRight },
        { key: "properties", title: "属性", icon: FileText, panelKey: "properties" },
        { key: "time", title: "时间", icon: Clock, panelKey: "time" },
        { key: "source", title: "来源", icon: Link2, panelKey: "source" },
        { key: "usage", title: "使用", icon: BriefcaseBusiness, panelKey: "usage" },
        // { key: "permission", title: "权限", icon: Lock, panelKey: "permission" },
        { key: "ai", title: "AI 对话" },
    ];

interface ToolRailProps {
    activePanel: PanelKey | null;
    aiOpen: boolean;
    onTogglePanel: () => void;
    onOpenAi: () => void;
    onOpenPanel: (panel: Extract<PanelKey, "properties" | "time" | "source" | "usage" | "permission">) => void;
}

export function ToolRail({
    activePanel,
    aiOpen,
    onTogglePanel,
    onOpenAi,
    onOpenPanel,
}: ToolRailProps) {
    const toolbarItems = TOOLBAR_ITEMS;

    return (
        <aside className={s.toolRail} data-testid="portal-tool-rail">
            {toolbarItems.map((item) => {
                const Icon = item.icon;
                const active = item.key === "ai"
                    ? aiOpen
                    : Boolean(item.panelKey && activePanel === item.panelKey);
                return (
                    <button
                        type="button"
                        key={item.key}
                        className={`${s.toolbarButton} ${item.key === "ai" ? s.toolbarButtonAi : ""} ${active ? s.toolbarButtonActive : ""}`}
                        title={item.title}
                        aria-label={item.title}
                        aria-pressed={active}
                        onClick={() => {
                            if (item.key === "toggle") {
                                onTogglePanel();
                                return;
                            }
                            if (item.key === "ai") {
                                onOpenAi();
                                return;
                            }
                            if (item.panelKey) {
                                onOpenPanel(item.panelKey);
                            }
                        }}
                    >
                        {item.key === "ai" ? (
                            <img
                                src={AI_ASSISTANT_ICON_SRC}
                                alt=""
                                aria-hidden="true"
                                className={s.toolRailAiIcon}
                            />
                        ) : Icon ? (
                            <Icon size={16} />
                        ) : null}
                    </button>
                );
            })}
        </aside>
    );
}
