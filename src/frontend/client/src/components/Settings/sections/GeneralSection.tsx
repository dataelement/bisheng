// Language state moved verbatim from UserPopMenu — store.lang is a frozen
// legacy atom (ledger #5), no new atoms added.
// eslint-disable-next-line no-restricted-imports
import { useRecoilState } from "recoil";
import { Select } from "@bisheng/ui";
import { useLocalize } from "~/hooks";
import useSelectCopy from "~/hooks/useSelectCopy";
import store from "~/store";
import { StorageSection } from "./StorageSection";

interface SettingSelectProps {
    value: string;
    options: { value: string; label: string }[];
    onValueChange: (value: string) => void;
    "aria-label"?: string;
}

/** Select for a settings row; fills the width its row gives it. */
export function SettingSelect({ value, options, onValueChange, "aria-label": ariaLabel }: SettingSelectProps) {
    const selectCopy = useSelectCopy();
    return (
        <Select
            {...selectCopy}
            options={options}
            value={value}
            onChange={(next) => next != null && onValueChange(String(next))}
            aria-label={ariaLabel}
            className="w-full"
        />
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
        // The section title is rendered by SettingsPage's unified pane header.
        <section className="flex flex-col gap-4">
            <StorageSection />

            <div className="flex items-center justify-between gap-4">
                <span className="text-[14px] text-[#1d2129]">{localize("com_nav_language")}</span>
                <div className="w-[160px] shrink-0">
                    <SettingSelect
                        value={normalizeLang(langcode)}
                        options={languages}
                        onValueChange={setLangcode}
                        aria-label={localize("com_nav_language")}
                    />
                </div>
            </div>
        </section>
    );
}
