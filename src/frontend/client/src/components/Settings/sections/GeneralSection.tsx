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
import { useLocalize } from "~/hooks";
import store from "~/store";
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

/** App-wide preferences: display language. */
export function GeneralSection() {
    const localize = useLocalize();
    const [langcode, setLangcode] = useRecoilState(store.lang);

    const languages = [
        { value: "zh-Hans", label: localize("com_settings_lang_zh") },
        { value: "en", label: localize("com_settings_lang_en") },
        ...(!window.APP_CONFIG?.disableJa
            ? [{ value: "ja", label: localize("com_settings_lang_ja") }]
            : []),
    ];

    return (
        <section className="flex flex-col gap-4">
            <h3 className="text-[14px] font-semibold leading-5 text-[#212121]">
                {localize("com_settings_general")}
            </h3>

            <StorageSection />

            <div className="flex items-center justify-between gap-4">
                <span className="text-[14px] text-[#1d2129]">{localize("com_nav_language")}</span>
                <div className="w-[160px] shrink-0">
                    <SettingSelect value={normalizeLang(langcode)} options={languages} onValueChange={setLangcode} />
                </div>
            </div>
        </section>
    );
}
