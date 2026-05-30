import { BriefcaseBusiness, Clock, FileText, Link2, LockKeyhole, PanelRight } from "lucide-react";
import type { PanelKey, PortalToolRailKey } from "../types";
import s from "../PortalKnowledgeWorkbench.module.css";

const TOOLBAR_ITEMS: Array<{
    key: PortalToolRailKey;
    title: string;
    icon: typeof PanelRight;
    panelKey?: Extract<PanelKey, "properties" | "time" | "source" | "usage" | "permission">;
}> = [
    { key: "toggle", title: "侧边栏展开和关闭", icon: PanelRight },
    { key: "properties", title: "属性", icon: FileText, panelKey: "properties" },
    { key: "time", title: "时间", icon: Clock, panelKey: "time" },
    { key: "source", title: "来源", icon: Link2, panelKey: "source" },
    { key: "usage", title: "使用", icon: BriefcaseBusiness, panelKey: "usage" },
    { key: "permission", title: "权限", icon: LockKeyhole, panelKey: "permission" },
];

interface ToolRailProps {
    activePanel: PanelKey | null;
    showPermissionPanel?: boolean;
    onTogglePanel: () => void;
    onOpenPanel: (panel: Extract<PanelKey, "properties" | "time" | "source" | "usage" | "permission">) => void;
}

export function ToolRail({
    activePanel,
    showPermissionPanel = true,
    onTogglePanel,
    onOpenPanel,
}: ToolRailProps) {
    const toolbarItems = showPermissionPanel
        ? TOOLBAR_ITEMS
        : TOOLBAR_ITEMS.filter((item) => item.panelKey !== "permission");

    return (
        <aside className={s.toolRail} data-testid="portal-tool-rail">
            {toolbarItems.map((item) => {
                const Icon = item.icon;
                const active = Boolean(item.panelKey && activePanel === item.panelKey);
                return (
                    <button
                        type="button"
                        key={item.key}
                        className={`${s.toolbarButton} ${active ? s.toolbarButtonActive : ""}`}
                        title={item.title}
                        aria-label={item.title}
                        aria-pressed={active}
                        onClick={() => {
                            if (item.key === "toggle") {
                                onTogglePanel();
                                return;
                            }
                            if (item.panelKey) {
                                onOpenPanel(item.panelKey);
                            }
                        }}
                    >
                        <Icon size={16} />
                    </button>
                );
            })}
        </aside>
    );
}
