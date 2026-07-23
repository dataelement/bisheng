import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useRecoilValue } from "recoil";

import store from "~/store";
import type { TUser } from "~/types/chat";
import styles from "./KnowledgePreviewWatermark.module.css";

const BEIJING_TIME_ZONE = "Asia/Shanghai";
const WATERMARK_FONT_SIZE = 16;
const WATERMARK_LINE_HEIGHT = 20;
const WATERMARK_ROTATION = -35;
const WATERMARK_OPACITY = 0.31;
const WATERMARK_MIN_CELL_WIDTH = 240;
const WATERMARK_MIN_CELL_HEIGHT = 180;
const WATERMARK_HORIZONTAL_CLEARANCE = 48;
const WATERMARK_VERTICAL_CLEARANCE = 36;
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

interface WatermarkLayout {
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
    anchorX: number;
    anchorY: number;
}

interface WatermarkPosition {
    x: number;
    y: number;
    rowIndex: number;
    columnIndex: number;
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

export function calculateKnowledgePreviewWatermarkLayout(
    lineWidths: readonly number[],
): WatermarkLayout {
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
        anchorX: WATERMARK_HORIZONTAL_CLEARANCE / 2,
        anchorY: WATERMARK_VERTICAL_CLEARANCE / 2 + textWidth * Math.sin(angle),
    };
}

export function calculateKnowledgePreviewWatermarkPositions(
    surfaceWidth: number,
    surfaceHeight: number,
    layout: WatermarkLayout,
): WatermarkPosition[] {
    if (
        !Number.isFinite(surfaceWidth)
        || !Number.isFinite(surfaceHeight)
        || surfaceWidth <= 0
        || surfaceHeight <= 0
    ) {
        return [];
    }

    const positions: WatermarkPosition[] = [];
    let rowIndex = 0;
    for (let rowTop = 0; rowTop < surfaceHeight; rowTop += layout.cellHeight) {
        const rowOffsetX = rowIndex % 2 === 0 ? 0 : layout.cellWidth / 2;
        let columnIndex = 0;
        for (
            let cellLeft = rowOffsetX;
            cellLeft + layout.anchorX < surfaceWidth;
            cellLeft += layout.cellWidth
        ) {
            positions.push({
                x: cellLeft + layout.anchorX,
                y: rowTop + layout.anchorY,
                rowIndex,
                columnIndex,
            });
            columnIndex += 1;
        }
        rowIndex += 1;
    }
    return positions;
}

export function formatKnowledgePreviewWatermarkTime(value: Date): string {
    const parts = new Intl.DateTimeFormat("en-CA", {
        timeZone: BEIJING_TIME_ZONE,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
    }).formatToParts(value);
    const values = new Map(parts.map((part) => [part.type, part.value]));
    return `${values.get("year")}/${values.get("month")}/${values.get("day")}`;
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

interface CurrentUserWatermarkSurfaceProps {
    children: ReactNode;
    className?: string;
    enabled?: boolean;
}

export function CurrentUserWatermarkSurface({
    children,
    className = "",
    enabled = false,
}: CurrentUserWatermarkSurfaceProps) {
    const user = useRecoilValue(store.user);
    if (!enabled || !user) return <>{children}</>;

    return (
        <KnowledgePreviewWatermarkProvider>
            <div
                className={`relative min-h-0 min-w-0 overflow-hidden ${className}`.trim()}
                data-chat-watermark-surface
            >
                {children}
                <KnowledgePreviewWatermark />
            </div>
        </KnowledgePreviewWatermarkProvider>
    );
}

export default function KnowledgePreviewWatermark() {
    const lines = useContext(KnowledgePreviewWatermarkContext);
    const overlayRef = useRef<HTMLDivElement>(null);
    const fallbackLayout = useMemo(
        () => calculateKnowledgePreviewWatermarkLayout(
            measureKnowledgePreviewWatermarkLineWidths(lines ?? []),
        ),
        [lines],
    );
    const [layout, setLayout] = useState(fallbackLayout);
    const [surfaceSize, setSurfaceSize] = useState({ width: 0, height: 0 });

    useEffect(() => {
        if (!lines) return undefined;
        let active = true;
        const updateLayout = () => {
            const next = calculateKnowledgePreviewWatermarkLayout(
                measureKnowledgePreviewWatermarkLineWidths(lines),
            );
            if (active) setLayout(next);
        };
        updateLayout();
        void document.fonts?.ready.then(updateLayout);
        return () => { active = false; };
    }, [lines]);

    useEffect(() => {
        const overlay = overlayRef.current;
        if (!overlay) return undefined;

        const updateSize = (width: number, height: number) => {
            setSurfaceSize((current) => (
                current.width === width && current.height === height
                    ? current
                    : { width, height }
            ));
        };
        const measure = () => {
            const rect = overlay.getBoundingClientRect();
            updateSize(rect.width, rect.height);
        };

        measure();
        if (typeof ResizeObserver === "undefined") return undefined;
        const observer = new ResizeObserver((entries) => {
            const entry = entries[0];
            if (entry) updateSize(entry.contentRect.width, entry.contentRect.height);
        });
        observer.observe(overlay);
        return () => observer.disconnect();
    }, [lines]);

    const positions = useMemo(
        () => calculateKnowledgePreviewWatermarkPositions(
            surfaceSize.width,
            surfaceSize.height,
            layout,
        ),
        [layout, surfaceSize.height, surfaceSize.width],
    );

    if (!lines) return null;

    return (
        <div ref={overlayRef} className={styles.overlay} aria-hidden="true">
            <svg className={styles.canvas} width="100%" height="100%">
                {positions.map((position) => (
                    <g
                        key={`${position.rowIndex}-${position.columnIndex}`}
                        transform={`translate(${position.x} ${position.y}) rotate(${layout.rotation})`}
                    >
                        <text className={styles.text} fillOpacity={layout.opacity} x="0" y={layout.fontSize}>{lines[0]}</text>
                        <text className={styles.text} fillOpacity={layout.opacity} x="0" y={layout.fontSize + layout.lineHeight}>{lines[1]}</text>
                    </g>
                ))}
            </svg>
        </div>
    );
}
