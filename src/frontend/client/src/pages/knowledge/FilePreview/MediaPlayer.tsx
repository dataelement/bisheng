/**
 * MediaPlayer — custom-skinned audio/video player for knowledge file preview.
 * Replaces the browser-native controls (whose icons/menu cannot be styled) with
 * a hand-rolled control bar driven by the standard HTMLMediaElement API.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode, SyntheticEvent } from "react";
import { Filled, Outlined } from "bisheng-icons";
import { DropdownMenu, DropdownMenuTrigger } from "~/components";
import { ActionMenuContent, ActionMenuItem } from "~/components/ActionMenu";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";

interface MediaPlayerProps {
    kind: "video" | "audio";
    src: string;
    allowDownload?: boolean;
    onDownload?: () => void;
}

const PLAYBACK_RATES = [0.5, 0.75, 1, 1.25, 1.5, 2];

function formatTime(seconds: number): string {
    if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
    const total = Math.floor(seconds);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = String(total % 60).padStart(2, "0");
    return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

const KEYBOARD_STEP = 0.05;

interface TrackBarProps {
    /** Filled portion, 0–1. */
    ratio: number;
    /** Absolute set — pointer drags and Home/End. */
    onChange: (ratio: number) => void;
    /** Relative step — arrow keys. Applied against the live media value, so
     *  repeated presses within one frame can't work off a stale `ratio`. */
    onNudge: (delta: number) => void;
    label: string;
    orientation?: "horizontal" | "vertical";
    disabled?: boolean;
    trackClassName: string;
    fillClassName: string;
}

/** Draggable/keyboard-operable bar shared by the seek and volume controls. */
function TrackBar({
    ratio,
    onChange,
    onNudge,
    label,
    orientation = "horizontal",
    disabled = false,
    trackClassName,
    fillClassName,
}: TrackBarProps) {
    const barRef = useRef<HTMLDivElement>(null);
    const vertical = orientation === "vertical";
    const clamped = Math.min(Math.max(ratio, 0), 1);

    const emitFromPointer = useCallback(
        (clientX: number, clientY: number) => {
            const bar = barRef.current;
            if (!bar || disabled) return;
            const rect = bar.getBoundingClientRect();
            const size = vertical ? rect.height : rect.width;
            if (size <= 0) return;
            const offset = vertical ? rect.bottom - clientY : clientX - rect.left;
            onChange(Math.min(Math.max(offset / size, 0), 1));
        },
        [disabled, onChange, vertical],
    );

    const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
        if (disabled) return;
        const decrease = vertical ? "ArrowDown" : "ArrowLeft";
        const increase = vertical ? "ArrowUp" : "ArrowRight";
        if (event.key === decrease) onNudge(-KEYBOARD_STEP);
        else if (event.key === increase) onNudge(KEYBOARD_STEP);
        else if (event.key === "Home") onChange(0);
        else if (event.key === "End") onChange(1);
        else return;
        event.preventDefault();
    };

    return (
        <div
            ref={barRef}
            role="slider"
            tabIndex={disabled ? -1 : 0}
            aria-label={label}
            aria-orientation={orientation}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(clamped * 100)}
            className={cn(
                "relative flex outline-none",
                vertical ? "h-full w-4 justify-center" : "h-4 min-w-0 flex-1 items-center",
                disabled ? "cursor-default" : "cursor-pointer",
            )}
            onPointerDown={(event) => {
                emitFromPointer(event.clientX, event.clientY);
                // Capture keeps the drag alive outside the bar; a browser that
                // refuses it must not cost us the initial jump above.
                try {
                    event.currentTarget.setPointerCapture(event.pointerId);
                } catch {
                    /* not capturable — click-to-set still works */
                }
            }}
            onPointerMove={(event) => {
                if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                    emitFromPointer(event.clientX, event.clientY);
                }
            }}
            onKeyDown={handleKeyDown}
        >
            <div
                className={cn(
                    "overflow-hidden rounded-full",
                    vertical ? "flex h-full w-1 flex-col justify-end" : "h-1 w-full",
                    trackClassName,
                )}
            >
                <div
                    className={cn("rounded-full", vertical ? "w-full" : "h-full", fillClassName)}
                    style={
                        vertical ? { height: `${clamped * 100}%` } : { width: `${clamped * 100}%` }
                    }
                />
            </div>
        </div>
    );
}

interface ControlButtonProps {
    label: string;
    onClick: () => void;
    className?: string;
    children: ReactNode;
}

function ControlButton({ label, onClick, className, children }: ControlButtonProps) {
    return (
        <button
            type="button"
            aria-label={label}
            title={label}
            onClick={onClick}
            className={cn(
                "flex size-7 shrink-0 items-center justify-center rounded-md transition-colors",
                className,
            )}
        >
            {children}
        </button>
    );
}

interface VolumeControlProps {
    /** Current output level, 0–1 (already 0 when muted). */
    level: number;
    muted: boolean;
    onChangeVolume: (level: number) => void;
    onNudgeVolume: (delta: number) => void;
    onToggleMute: () => void;
    tone: "dark" | "light";
}

/** Mute toggle plus a vertical volume slider revealed on hover / keyboard focus. */
function VolumeControl({
    level,
    muted,
    onChangeVolume,
    onNudgeVolume,
    onToggleMute,
    tone,
}: VolumeControlProps) {
    const localize = useLocalize();
    const dark = tone === "dark";
    const silent = muted || level === 0;

    return (
        <div className="group/volume relative flex shrink-0 items-center">
            <ControlButton
                label={silent ? localize("com_knowledge.unmute") : localize("com_knowledge.mute")}
                onClick={onToggleMute}
                className={dark ? "hover:bg-white/20" : "hover:bg-fill-3"}
            >
                {silent ? (
                    <Outlined.VolumeMute className="size-4" />
                ) : (
                    <Outlined.VolumeNotice className="size-4" />
                )}
            </ControlButton>
            <div
                className={cn(
                    "invisible absolute bottom-full left-1/2 z-20 -translate-x-1/2 pb-1.5 opacity-0 transition-opacity",
                    "group-hover/volume:visible group-hover/volume:opacity-100",
                    "group-focus-within/volume:visible group-focus-within/volume:opacity-100",
                )}
            >
                <div
                    className={cn(
                        "flex h-[88px] w-7 items-center justify-center rounded-full py-3",
                        dark
                            ? "bg-black/80"
                            : "bg-white shadow-[0_2px_16px_-2px_rgba(0,23,66,0.10)]",
                    )}
                >
                    <TrackBar
                        ratio={level}
                        onChange={onChangeVolume}
                        onNudge={onNudgeVolume}
                        label={localize("com_knowledge.volume")}
                        orientation="vertical"
                        trackClassName={dark ? "bg-white/30" : "bg-fill-3"}
                        fillClassName={dark ? "bg-white" : "bg-blue-500"}
                    />
                </div>
            </div>
        </div>
    );
}

export function MediaPlayer({ kind, src, allowDownload = false, onDownload }: MediaPlayerProps) {
    const localize = useLocalize();
    const isVideo = kind === "video";
    const containerRef = useRef<HTMLDivElement>(null);
    const mediaRef = useRef<HTMLVideoElement | HTMLAudioElement | null>(null);
    const [playing, setPlaying] = useState(false);
    const [currentTime, setCurrentTime] = useState(0);
    const [duration, setDuration] = useState(0);
    const [muted, setMuted] = useState(false);
    const [volume, setVolume] = useState(1);
    const [rate, setRate] = useState(1);
    const [fullscreen, setFullscreen] = useState(false);
    /** Level to restore when unmuting from a zero-volume state. */
    const lastVolumeRef = useRef(1);

    const pipSupported =
        isVideo && typeof document !== "undefined" && Boolean(document.pictureInPictureEnabled);

    useEffect(() => {
        const handleChange = () =>
            setFullscreen(document.fullscreenElement === containerRef.current);
        document.addEventListener("fullscreenchange", handleChange);
        return () => document.removeEventListener("fullscreenchange", handleChange);
    }, []);

    const togglePlay = useCallback(() => {
        const media = mediaRef.current;
        if (!media) return;
        if (media.paused) {
            void media.play();
        } else {
            media.pause();
        }
    }, []);

    const toggleMute = useCallback(() => {
        const media = mediaRef.current;
        if (!media) return;
        if (media.muted || media.volume === 0) {
            media.muted = false;
            if (media.volume === 0) media.volume = lastVolumeRef.current || 1;
        } else {
            lastVolumeRef.current = media.volume;
            media.muted = true;
        }
    }, []);

    const changeVolume = useCallback((next: number) => {
        const media = mediaRef.current;
        if (!media) return;
        media.volume = next;
        if (next > 0) {
            media.muted = false;
            lastVolumeRef.current = next;
        }
    }, []);

    const toggleFullscreen = useCallback(() => {
        const container = containerRef.current;
        if (!container) return;
        if (document.fullscreenElement === container) {
            void document.exitFullscreen();
        } else {
            void container.requestFullscreen();
        }
    }, []);

    const togglePictureInPicture = useCallback(() => {
        const media = mediaRef.current;
        if (!media || !(media instanceof HTMLVideoElement)) return;
        if (document.pictureInPictureElement === media) {
            void document.exitPictureInPicture();
        } else {
            void media.requestPictureInPicture();
        }
    }, []);

    const changeRate = useCallback((next: number) => {
        const media = mediaRef.current;
        if (media) media.playbackRate = next;
        setRate(next);
    }, []);

    const nudgeVolume = useCallback(
        (delta: number) => {
            const media = mediaRef.current;
            if (!media) return;
            const current = media.muted ? 0 : media.volume;
            changeVolume(Math.min(Math.max(current + delta, 0), 1));
        },
        [changeVolume],
    );

    const seekTo = useCallback((time: number) => {
        const media = mediaRef.current;
        if (!media) return;
        media.currentTime = time;
        setCurrentTime(time);
    }, []);

    const nudgeSeek = useCallback((deltaRatio: number) => {
        const media = mediaRef.current;
        if (!media || !Number.isFinite(media.duration) || media.duration <= 0) return;
        const next = media.currentTime + deltaRatio * media.duration;
        const clamped = Math.min(Math.max(next, 0), media.duration);
        media.currentTime = clamped;
        setCurrentTime(clamped);
    }, []);

    const mediaEvents = {
        onPlay: () => setPlaying(true),
        onPause: () => setPlaying(false),
        onEnded: () => setPlaying(false),
        onTimeUpdate: (event: SyntheticEvent<HTMLMediaElement>) =>
            setCurrentTime(event.currentTarget.currentTime),
        onLoadedMetadata: (event: SyntheticEvent<HTMLMediaElement>) =>
            setDuration(event.currentTarget.duration || 0),
        onDurationChange: (event: SyntheticEvent<HTMLMediaElement>) =>
            setDuration(event.currentTarget.duration || 0),
        onVolumeChange: (event: SyntheticEvent<HTMLMediaElement>) => {
            setMuted(event.currentTarget.muted);
            setVolume(event.currentTarget.volume);
        },
        onRateChange: (event: SyntheticEvent<HTMLMediaElement>) =>
            setRate(event.currentTarget.playbackRate),
    };

    const speedMenu = (trigger: ReactNode) => (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
            <ActionMenuContent width={96} align="end" side="top" className={menuSurfaceClass}>
                {PLAYBACK_RATES.map((value) => (
                    <ActionMenuItem
                        key={value}
                        onClick={() => changeRate(value)}
                        className={cn(menuItemClass, value === rate && activeRateClass)}
                        label={`${value}x`}
                    />
                ))}
            </ActionMenuContent>
        </DropdownMenu>
    );

    const showMoreMenu = allowDownload || pipSupported;
    /* Video plays on a black stage with white controls over a scrim; audio has no
       picture, so it uses the design-system neutral fill with dark controls. */
    const onDarkStage = isVideo;
    const hoverClass = onDarkStage ? "hover:bg-white/20" : "hover:bg-fill-3";
    const iconButtonClass = cn(
        "flex size-7 shrink-0 items-center justify-center rounded-md transition-colors",
        hoverClass,
    );
    /* Menus float over the media, so they stay translucent and open upward
       rather than covering the stage below the bar. */
    const menuSurfaceClass = onDarkStage
        ? "border-0 bg-black/75 backdrop-blur-md"
        : "bg-white/85 backdrop-blur-md";
    /* The shared menu item forces a dark label while highlighted, which is
       unreadable on the dark surface — keep it white on hover/focus too. */
    const menuItemClass = onDarkStage
        ? cn(
              "text-white data-[highlighted]:bg-white/20 data-[highlighted]:text-white",
              "focus:bg-white/20 focus:text-white",
          )
        : undefined;
    const menuIconClass = onDarkStage ? "text-white/80" : undefined;
    const activeRateClass = onDarkStage
        ? "font-medium text-blue-400"
        : "font-medium text-blue-500";

    return (
        <div
            ref={containerRef}
            className={cn(
                "relative overflow-hidden",
                onDarkStage ? "bg-black" : "bg-fill-2",
                fullscreen ? "flex h-full w-full flex-col justify-center" : "rounded-[6px]",
            )}
        >
            {isVideo ? (
                <video
                    ref={(node) => {
                        mediaRef.current = node;
                    }}
                    className={cn("w-full", fullscreen ? "min-h-0 flex-1" : "max-h-[60vh]")}
                    src={src}
                    playsInline
                    onClick={togglePlay}
                    {...mediaEvents}
                />
            ) : (
                <>
                    {/* Audio carries no picture — a placeholder keeps the same
                            stage shape (and control bar) as the video player. */}
                    <div
                        className="flex h-[200px] w-full items-center justify-center"
                        onClick={togglePlay}
                    >
                        <Outlined.FileAudio className="size-12 text-text-4" />
                    </div>
                    <audio
                        ref={(node) => {
                            mediaRef.current = node;
                        }}
                        src={src}
                        {...mediaEvents}
                    />
                </>
            )}
            <div
                className={cn(
                    "absolute inset-x-0 bottom-0 flex items-center gap-3 px-3 pb-2 pt-8",
                    onDarkStage
                        ? "bg-gradient-to-t from-black/70 to-transparent text-white"
                        : "text-text-2",
                )}
            >
                <ControlButton
                    label={
                        playing ? localize("com_knowledge.pause") : localize("com_knowledge.play")
                    }
                    onClick={togglePlay}
                    className={cn(onDarkStage ? "" : "text-text-1", hoverClass)}
                >
                    {playing ? (
                        <Filled.PlayerPause className="size-5" />
                    ) : (
                        <Filled.PlayerPlay className="size-5" />
                    )}
                </ControlButton>
                <span className={cn("shrink-0 tabular-nums text-caption", onDarkStage ? "text-white/90" : "text-text-3")}>
                    {formatTime(currentTime)} / {formatTime(duration)}
                </span>
                <TrackBar
                    ratio={duration > 0 ? currentTime / duration : 0}
                    onChange={(r) => seekTo(r * duration)}
                    onNudge={nudgeSeek}
                    label={localize("com_knowledge.progress")}
                    disabled={duration <= 0}
                    trackClassName={onDarkStage ? "bg-white/30" : "bg-fill-3"}
                    fillClassName={onDarkStage ? "bg-white" : "bg-blue-500"}
                />
                <VolumeControl
                    level={muted ? 0 : volume}
                    muted={muted}
                    onChangeVolume={changeVolume}
                    onNudgeVolume={nudgeVolume}
                    onToggleMute={toggleMute}
                    tone={onDarkStage ? "dark" : "light"}
                />
                {speedMenu(
                    <button
                        type="button"
                        aria-label={localize("com_knowledge.playback_speed")}
                        title={localize("com_knowledge.playback_speed")}
                        className={iconButtonClass}
                    >
                        <Outlined.PlaySpeed className="size-4" />
                    </button>,
                )}
                {/* Fullscreen and picture-in-picture only make sense for video. */}
                {isVideo && (
                    <ControlButton
                        label={
                            fullscreen
                                ? localize("com_knowledge.exit_fullscreen")
                                : localize("com_knowledge.fullscreen")
                        }
                        onClick={toggleFullscreen}
                        className={hoverClass}
                    >
                        {fullscreen ? (
                            <Outlined.ExitFullScreen className="size-4" />
                        ) : (
                            <Outlined.FullScreen className="size-4" />
                        )}
                    </ControlButton>
                )}
                {showMoreMenu && (
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <button
                                type="button"
                                aria-label={localize("com_knowledge.more")}
                                title={localize("com_knowledge.more")}
                                className={iconButtonClass}
                            >
                                <Outlined.More className="size-4" />
                            </button>
                        </DropdownMenuTrigger>
                        <ActionMenuContent align="end" side="top" className={menuSurfaceClass}>
                            {allowDownload && (
                                <ActionMenuItem
                                    onClick={onDownload}
                                    icon={<Outlined.Download className={menuIconClass} />}
                                    label={localize("com_knowledge.download")}
                                    className={menuItemClass}
                                />
                            )}
                            {pipSupported && (
                                <ActionMenuItem
                                    onClick={togglePictureInPicture}
                                    icon={<Outlined.PictureInPicture className={menuIconClass} />}
                                    label={localize("com_knowledge.picture_in_picture")}
                                    className={menuItemClass}
                                />
                            )}
                        </ActionMenuContent>
                    </DropdownMenu>
                )}
            </div>
        </div>
    );
}
