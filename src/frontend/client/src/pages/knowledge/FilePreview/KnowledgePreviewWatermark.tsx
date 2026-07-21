import { createContext, useContext, useState, type ReactNode } from "react";
import { useRecoilValue } from "recoil";

import store from "~/store";
import type { TUser } from "~/types/chat";
import styles from "./KnowledgePreviewWatermark.module.css";

const BEIJING_TIME_ZONE = "Asia/Shanghai";
const WATERMARK_TILE_COUNT = 24;

type KnowledgePreviewWatermarkUser = Pick<TUser, "name" | "username" | "departmentName">;

const KnowledgePreviewWatermarkContext = createContext<string[] | null>(null);

export function formatKnowledgePreviewWatermarkTime(value: Date): string {
    const parts = new Intl.DateTimeFormat("en-CA", {
        timeZone: BEIJING_TIME_ZONE,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
    }).formatToParts(value);
    const values = new Map(parts.map((part) => [part.type, part.value]));
    return `${values.get("year")}-${values.get("month")}-${values.get("day")}`;
}

export function buildKnowledgePreviewWatermarkLines(
    user: KnowledgePreviewWatermarkUser,
    viewedAt: Date,
): string[] {
    const name = user.name.trim() || user.username.trim() || "未知用户";
    const departmentName = user.departmentName?.trim() || "";
    return [
        departmentName ? `${departmentName}-${name}` : name,
        formatKnowledgePreviewWatermarkTime(viewedAt),
        "首钢集团内部资料",
    ];
}

export function KnowledgePreviewWatermarkProvider({ children }: { children: ReactNode }) {
    const user = useRecoilValue(store.user);
    const [viewedAt] = useState(() => new Date());
    const lines = user ? buildKnowledgePreviewWatermarkLines(user, viewedAt) : null;

    return (
        <KnowledgePreviewWatermarkContext.Provider value={lines}>
            {children}
        </KnowledgePreviewWatermarkContext.Provider>
    );
}

export default function KnowledgePreviewWatermark() {
    const lines = useContext(KnowledgePreviewWatermarkContext);

    if (!lines) return null;

    return (
        <div className={styles.overlay} aria-hidden="true">
            {Array.from({ length: WATERMARK_TILE_COUNT }, (_, index) => (
                <div className={styles.tile} key={index}>
                    {lines.map((line) => <span key={line}>{line}</span>)}
                </div>
            ))}
        </div>
    );
}
