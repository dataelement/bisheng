import { BriefcaseBusiness, Clock, FileText, History, Link2, MessageSquareWarning, PanelRight } from "lucide-react";
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
        { key: "correction", title: "纠错", icon: MessageSquareWarning },
        { key: "ai", title: "AI 对话" },
    ];

interface ToolRailProps {
    activePanel: PanelKey | null;
    aiOpen: boolean;
    showCorrection?: boolean;
    correctionOpen?: boolean;
    onOpenCorrection?: () => void;
    showCorrectionHistory?: boolean;
    correctionHistoryOpen?: boolean;
    onOpenCorrectionHistory?: () => void;
    onTogglePanel: () => void;
    onOpenAi: () => void;
    onOpenPanel: (panel: Extract<PanelKey, "properties" | "time" | "source" | "usage" | "permission">) => void;
}

/** 阅读页右侧固定工具栏. 纠错入口放这里, 避免随文档预览滚动被顶出视口. */
export function ToolRail({
    activePanel,
    aiOpen,
    showCorrection = false,
    correctionOpen = false,
    onOpenCorrection,
    showCorrectionHistory = false,
    correctionHistoryOpen = false,
    onOpenCorrectionHistory,
    onTogglePanel,
    onOpenAi,
    onOpenPanel,
}: ToolRailProps) {
    const toolbarItems = TOOLBAR_ITEMS;

    return (
        <aside className={s.toolRail} data-testid="portal-tool-rail">
            {toolbarItems.map((item) => {
                if (item.key === "correction" && !showCorrection) return null;
                const Icon = item.icon;
                const active = item.key === "ai"
                    ? aiOpen
                    : item.key === "correction"
                        ? correctionOpen
                        : Boolean(item.panelKey && activePanel === item.panelKey);
                const historyButton = item.key === "ai" && showCorrectionHistory ? (
                    <button
                        type="button"
                        key="correction-history"
                        className={`${s.toolbarButton} ${correctionHistoryOpen ? s.toolbarButtonActive : ""}`}
                        title="纠错历史"
                        aria-label="纠错历史"
                        aria-pressed={correctionHistoryOpen}
                        onClick={onOpenCorrectionHistory}
                    >
                        <History size={16} />
                    </button>
                ) : null;
                return (
                    <span key={item.key} className="contents">
                    {historyButton}
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
                            if (item.key === "correction") {
                                onOpenCorrection?.();
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
                    </span>
                );
            })}
        </aside>
    );
}
