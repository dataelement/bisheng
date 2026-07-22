import { createContext, useContext, useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { useRecoilValue } from "recoil";

import store from "~/store";
import type { TUser } from "~/types/chat";
import styles from "./KnowledgePreviewWatermark.module.css";

const BEIJING_TIME_ZONE = "Asia/Shanghai";
const WATERMARK_FONT_SIZE = 16;
const WATERMARK_LINE_HEIGHT = 20;
const WATERMARK_ROTATION = -35;
const WATERMARK_OPACITY = 0.11;
const WATERMARK_MIN_CELL_WIDTH = 384;
const WATERMARK_MIN_CELL_HEIGHT = 267;
const WATERMARK_HORIZONTAL_CLEARANCE = 64;
const WATERMARK_VERTICAL_CLEARANCE = 48;
const WATERMARK_FONT_FAMILY = [
    '"WenQuanYi Zen Hei"',
    '"Microsoft YaHei"',
    '"PingFang SC"',
    '"Noto Sans CJK SC"',
    "sans-serif",
].join(", ");

type KnowledgePreviewWatermarkUser = Pick<
    TUser,
    "name" | "username" | "departmentName" | "externalId"
>;

interface WatermarkPatternLayout {
    fontSize: number;
    lineHeight: number;
    rotation: number;
    opacity: number;
    textWidth: number;
    blockHeight: number;
    rotatedWidth: number;
    rotatedHeight: number;
    cellWidth: number;
    cellHeight: number;
    patternHeight: number;
    secondRowOffsetX: number;
    anchorX: number;
    anchorY: number;
}

const KnowledgePreviewWatermarkContext = createContext<string[] | null>(null);

function estimateKnowledgePreviewWatermarkLineWidth(line: string): number {
    return [...line].reduce((width, character) => (
        width + ((character.codePointAt(0) ?? 0) <= 0xff ? WATERMARK_FONT_SIZE * 0.62 : WATERMARK_FONT_SIZE)
    ), 0);
}

function measureKnowledgePreviewWatermarkLineWidths(lines: readonly string[]): number[] {
    const fallback = lines.map(estimateKnowledgePreviewWatermarkLineWidth);
    if (typeof document === "undefined") return fallback;
    if (typeof navigator !== "undefined" && /jsdom/i.test(navigator.userAgent)) return fallback;
    try {
        const context = document.createElement("canvas").getContext("2d");
        if (!context) return fallback;
        context.font = `${WATERMARK_FONT_SIZE}px ${WATERMARK_FONT_FAMILY}`;
        return lines.map((line) => context.measureText(line).width);
    } catch {
        return fallback;
    }
}

export function calculateKnowledgePreviewWatermarkPatternLayout(
    lineWidths: readonly number[],
): WatermarkPatternLayout {
    const textWidth = Math.max(0, ...lineWidths.filter(Number.isFinite));
    const blockHeight = WATERMARK_LINE_HEIGHT * 2;
    const angle = Math.abs(WATERMARK_ROTATION) * Math.PI / 180;
    const rotatedWidth = textWidth * Math.cos(angle) + blockHeight * Math.sin(angle);
    const rotatedHeight = textWidth * Math.sin(angle) + blockHeight * Math.cos(angle);
    const cellWidth = Math.max(
        WATERMARK_MIN_CELL_WIDTH,
        Math.ceil(rotatedWidth + WATERMARK_HORIZONTAL_CLEARANCE),
    );
    const cellHeight = Math.max(
        WATERMARK_MIN_CELL_HEIGHT,
        Math.ceil(rotatedHeight + WATERMARK_VERTICAL_CLEARANCE),
    );
    return {
        fontSize: WATERMARK_FONT_SIZE,
        lineHeight: WATERMARK_LINE_HEIGHT,
        rotation: WATERMARK_ROTATION,
        opacity: WATERMARK_OPACITY,
        textWidth,
        blockHeight,
        rotatedWidth,
        rotatedHeight,
        cellWidth,
        cellHeight,
        patternHeight: cellHeight * 2,
        secondRowOffsetX: cellWidth / 2,
        anchorX: WATERMARK_HORIZONTAL_CLEARANCE / 2,
        anchorY: WATERMARK_VERTICAL_CLEARANCE / 2 + textWidth * Math.sin(angle),
    };
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
    const patternId = `knowledge-preview-watermark-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
    const fallbackLayout = useMemo(
        () => calculateKnowledgePreviewWatermarkPatternLayout(
            measureKnowledgePreviewWatermarkLineWidths(lines ?? []),
        ),
        [lines],
    );
    const [layout, setLayout] = useState(fallbackLayout);

    useEffect(() => {
        if (!lines) return undefined;
        let active = true;
        const updateLayout = () => {
            const next = calculateKnowledgePreviewWatermarkPatternLayout(
                measureKnowledgePreviewWatermarkLineWidths(lines),
            );
            if (active) setLayout(next);
        };
        updateLayout();
        void document.fonts?.ready.then(updateLayout);
        return () => { active = false; };
    }, [lines]);

    if (!lines) return null;

    return (
        <div className={styles.overlay} aria-hidden="true">
            <svg className={styles.patternCanvas} width="100%" height="100%">
                <defs>
                    <pattern
                        id={patternId}
                        patternUnits="userSpaceOnUse"
                        width={layout.cellWidth}
                        height={layout.patternHeight}
                        overflow="visible"
                    >
                        <g transform={`translate(${layout.anchorX} ${layout.anchorY}) rotate(${layout.rotation})`}>
                            <text className={styles.text} x="0" y={layout.fontSize}>{lines[0]}</text>
                            <text className={styles.text} x="0" y={layout.fontSize + layout.lineHeight}>{lines[1]}</text>
                        </g>
                        <g transform={`translate(${layout.anchorX + layout.secondRowOffsetX} ${layout.cellHeight + layout.anchorY}) rotate(${layout.rotation})`}>
                            <text className={styles.text} x="0" y={layout.fontSize}>{lines[0]}</text>
                            <text className={styles.text} x="0" y={layout.fontSize + layout.lineHeight}>{lines[1]}</text>
                        </g>
                    </pattern>
                </defs>
                <rect width="100%" height="100%" fill={`url(#${patternId})`} />
            </svg>
        </div>
    );
}
