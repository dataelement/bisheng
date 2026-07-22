import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useRecoilValue } from "recoil";

import store from "~/store";
import type { TUser } from "~/types/chat";
import styles from "./KnowledgePreviewWatermark.module.css";

const BEIJING_TIME_ZONE = "Asia/Shanghai";
const WATERMARK_HORIZONTAL_STEP = 240;
const WATERMARK_VERTICAL_STEP = 160;

type KnowledgePreviewWatermarkUser = Pick<
    TUser,
    "name" | "username" | "departmentName" | "externalId"
>;

interface WatermarkGrid {
    columns: number;
    rows: number;
    tileCount: number;
}

const KnowledgePreviewWatermarkContext = createContext<string[] | null>(null);

export function calculateKnowledgePreviewWatermarkGrid(width: number, height: number): WatermarkGrid {
    const safeWidth = Number.isFinite(width) ? Math.max(width, 0) : 0;
    const safeHeight = Number.isFinite(height) ? Math.max(height, 0) : 0;
    const columns = Math.max(2, Math.ceil(safeWidth / WATERMARK_HORIZONTAL_STEP) + 1);
    const rows = Math.max(2, Math.ceil(safeHeight / WATERMARK_VERTICAL_STEP) + 1);
    return { columns, rows, tileCount: columns * rows };
}

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
    const account = user.externalId?.trim() || user.username.trim() || name;
    const departmentName = user.departmentName?.trim() || "";
    const identity = departmentName ? `${departmentName}-${name}` : name;
    return [
        `${identity}--${account}-${formatKnowledgePreviewWatermarkTime(viewedAt)}`,
        "首钢股份内部资料，严禁外传，违者必究",
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
    const hasLines = lines !== null;
    const overlayRef = useRef<HTMLDivElement>(null);
    const [grid, setGrid] = useState(() => calculateKnowledgePreviewWatermarkGrid(0, 0));

    useEffect(() => {
        const overlay = overlayRef.current;
        if (!overlay) return undefined;

        const updateGrid = (width: number, height: number) => {
            const next = calculateKnowledgePreviewWatermarkGrid(width, height);
            setGrid((current) => (
                current.columns === next.columns && current.rows === next.rows ? current : next
            ));
        };
        const initialRect = overlay.getBoundingClientRect();
        updateGrid(initialRect.width, initialRect.height);

        if (typeof ResizeObserver === "undefined") return undefined;
        const observer = new ResizeObserver((entries) => {
            const rect = entries[0]?.contentRect ?? overlay.getBoundingClientRect();
            updateGrid(rect.width, rect.height);
        });
        observer.observe(overlay);
        return () => observer.disconnect();
    }, [hasLines]);

    if (!lines) return null;

    return (
        <div
            ref={overlayRef}
            className={styles.overlay}
            aria-hidden="true"
            style={{ gridTemplateColumns: `repeat(${grid.columns}, ${WATERMARK_HORIZONTAL_STEP}px)` }}
        >
            {Array.from({ length: grid.tileCount }, (_, index) => (
                <div className={styles.tile} key={index}>
                    {lines.map((line) => <span className={styles.line} key={line}>{line}</span>)}
                </div>
            ))}
        </div>
    );
}
