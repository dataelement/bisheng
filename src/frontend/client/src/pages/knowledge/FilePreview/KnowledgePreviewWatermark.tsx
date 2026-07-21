import { useState } from "react";
import { useRecoilValue } from "recoil";

import store from "~/store";
import type { TUser } from "~/types/chat";
import styles from "./KnowledgePreviewWatermark.module.css";

const BEIJING_TIME_ZONE = "Asia/Shanghai";
const WATERMARK_TILE_COUNT = 24;

type KnowledgePreviewWatermarkUser = Pick<TUser, "name" | "username">;

export function formatKnowledgePreviewWatermarkTime(value: Date): string {
    const parts = new Intl.DateTimeFormat("en-CA", {
        timeZone: BEIJING_TIME_ZONE,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hourCycle: "h23",
    }).formatToParts(value);
    const values = new Map(parts.map((part) => [part.type, part.value]));
    return `${values.get("year")}-${values.get("month")}-${values.get("day")} ${values.get("hour")}:${values.get("minute")}:${values.get("second")}`;
}

export function buildKnowledgePreviewWatermarkLines(
    user: KnowledgePreviewWatermarkUser,
    viewedAt: Date,
): string[] {
    const account = user.username.trim();
    const name = user.name.trim() || account || "未知用户";
    return [
        `姓名：${name}`,
        `工号/账号：${account || "—"}`,
        `北京时间：${formatKnowledgePreviewWatermarkTime(viewedAt)}`,
        "首钢集团内部资料",
    ];
}

export default function KnowledgePreviewWatermark() {
    const user = useRecoilValue(store.user);
    const [viewedAt] = useState(() => new Date());

    if (!user) return null;
    const lines = buildKnowledgePreviewWatermarkLines(user, viewedAt);

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
