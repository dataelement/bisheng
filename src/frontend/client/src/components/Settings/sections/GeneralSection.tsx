// Language state moved verbatim from UserPopMenu — store.lang is a frozen
// legacy atom (ledger #5), no new atoms added.
// eslint-disable-next-line no-restricted-imports
import { useRecoilState } from "recoil";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "~/components/ui/Select";
import { useSyncExternalStore, useState } from "react";
import { useLocalize } from "~/hooks";
import store from "~/store";
import {
    FONT_SIZE_LEVELS,
    getFontSizeLevel,
    isFontSizeAvailable,
    saveFontSizeLevel,
    subscribeFontSizeAvailability,
    type FontSizeLevel,
} from "~/utils/fontSize";
import { cn } from "~/utils";
import { StorageSection } from "./StorageSection";

interface SettingSelectProps {
    value: string;
    options: { value: string; label: string }[];
    onValueChange: (value: string) => void;
}

/**
 * Select flavor for settings rows. The base SelectTrigger uses `focus:` for its
 * ring, and Radix returns focus to the trigger when the popup closes — so after
 * a mouse pick the trigger kept an "active" border. `focus-visible:` keeps the
 * ring for keyboard navigation only.
 */
export function SettingSelect({ value, options, onValueChange }: SettingSelectProps) {
    return (
        <Select value={value} onValueChange={onValueChange}>
            {/* Match the subscription source-filter trigger (MultiSourceSelect):
                outlined-button look — #ECECEC border, white bg, gray-800 text,
                gray-tint hover — instead of the base input-like trigger. */}
            <SelectTrigger className="h-8 w-full justify-between rounded-md border-[#ECECEC] bg-white px-3 text-sm font-normal text-gray-800 shadow-none transition-colors hover:bg-btn-fill-1 focus:ring-0 focus-visible:ring-1 focus-visible:ring-ring">
                <SelectValue />
            </SelectTrigger>
            <SelectContent
                className="z-[120] rounded-xl bg-white"
                viewportClassName="flex flex-col gap-0.5 p-2"
            >
                {options.map((option) => (
                    <SelectItem key={option.value} value={option.value} className="h-8 rounded-lg">
                        {option.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    );
}


interface SettingSegmentedProps<T extends string> {
    value: T;
    options: { value: T; label: string }[];
    onValueChange: (value: T) => void;
    ariaLabel: string;
}

/**
 * Segmented control for settings rows with few, always-visible options.
 *
 * Deliberately not a Select: picking a font size rescales the whole page — the
 * open Settings dialog included — and a Select would be doing that with its own
 * popup open, re-running the flyout positioning this branch has already had to
 * fix twice. A segmented control never opens a layer, so the rescale happens
 * with nothing floating above it.
 */
function SettingSegmented<T extends string>({ value, options, onValueChange, ariaLabel }: SettingSegmentedProps<T>) {
    return (
        <div role="radiogroup" aria-label={ariaLabel} className="flex h-8 min-w-[160px] items-center gap-0.5 rounded-md border border-[#ECECEC] bg-white p-0.5">
            {options.map((option) => {
                const active = option.value === value;
                return (
                    <button
                        key={option.value}
                        type="button"
                        role="radio"
                        aria-checked={active}
                        onClick={() => onValueChange(option.value)}
                        className={cn(
                            "h-full flex-1 whitespace-nowrap rounded px-2 text-sm font-normal transition-colors",
                            active ? "bg-blue-500/[0.07] text-blue-500" : "text-gray-800 hover:bg-btn-fill-1",
                        )}
                    >
                        {option.label}
                    </button>
                );
            })}
        </div>
    );
}

/**
 * store.lang can hold legacy un-normalized values (e.g. "zh-CN" restored from
 * localStorage, bypassing defaultLang's normalization) — map them onto the
 * three offered options so the Select never renders an empty value.
 */
function normalizeLang(lang: string | undefined): string {
    const lower = (lang ?? "").toLowerCase();
    if (lower.startsWith("zh")) return "zh-Hans";
    if (lower.startsWith("ja") && !window.APP_CONFIG?.disableJa) return "ja";
    return "en";
}

/** App-wide preferences: page font size (desktop only) and display language. */
export function GeneralSection() {
    const localize = useLocalize();
    const [langcode, setLangcode] = useRecoilState(store.lang);
    // Desktop-only: the zoom itself is gated on the same breakpoint, so the row
    // disappears rather than offering a control that would do nothing.
    const fontSizeAvailable = useSyncExternalStore(
        subscribeFontSizeAvailability,
        isFontSizeAvailable,
        () => false,
    );
    const [fontSizeLevel, setFontSizeLevel] = useState<FontSizeLevel>(() => getFontSizeLevel());
    const changeFontSize = (level: FontSizeLevel) => {
        if (saveFontSizeLevel(level)) {
            setFontSizeLevel(level);
        }
    };
    const fontSizeOptions = FONT_SIZE_LEVELS.map((level) => ({
        value: level,
        label: localize(`com_nav_page_font_size_${level}`),
    }));

    const languages = [
        { value: "zh-Hans", label: localize("com_settings_lang_zh") },
        { value: "en", label: localize("com_settings_lang_en") },
        ...(!window.APP_CONFIG?.disableJa
            ? [{ value: "ja", label: localize("com_settings_lang_ja") }]
            : []),
    ];

    return (
        // The section title is rendered by SettingsPage's unified pane header.
        <section className="flex flex-col gap-4">
            <StorageSection />

            {fontSizeAvailable && (
                <div className="flex items-center justify-between gap-4">
                    <span className="text-[14px] text-[#1d2129]">{localize("com_nav_page_font_size")}</span>
                    <div className="shrink-0">
                        <SettingSegmented
                            value={fontSizeLevel}
                            options={fontSizeOptions}
                            onValueChange={changeFontSize}
                            ariaLabel={localize("com_nav_page_font_size")}
                        />
                    </div>
                </div>
            )}

            <div className="flex items-center justify-between gap-4">
                <span className="text-[14px] text-[#1d2129]">{localize("com_nav_language")}</span>
                <div className="w-[160px] shrink-0">
                    <SettingSelect value={normalizeLang(langcode)} options={languages} onValueChange={setLangcode} />
                </div>
            </div>
        </section>
    );
}
