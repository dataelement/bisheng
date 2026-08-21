import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

export type SettingsSection = "account" | "general";

const SECTIONS: readonly SettingsSection[] = ["account", "general"];

export interface UseSettingsDialogResult {
    open: boolean;
    setOpen: (open: boolean) => void;
    section: SettingsSection;
    setSection: (section: SettingsSection) => void;
    openSettings: (section?: SettingsSection) => void;
}

/**
 * Settings dialog state, deep-linkable via `?open-settings=<section>` so flows
 * like the storage-quota warning can land the user on the right section
 * (same URL pattern as useNotificationsFromUrl).
 */
export function useSettingsDialog(): UseSettingsDialogResult {
    const [searchParams, setSearchParams] = useSearchParams();
    const rawParam = searchParams.get("open-settings");
    const urlSection = SECTIONS.includes(rawParam as SettingsSection)
        ? (rawParam as SettingsSection)
        : null;

    const [open, setOpen] = useState<boolean>(() => urlSection != null);
    const [section, setSection] = useState<SettingsSection>(urlSection ?? "account");

    useEffect(() => {
        if (rawParam == null) return;
        if (urlSection) {
            setSection(urlSection);
            setOpen(true);
        }
        const next = new URLSearchParams(searchParams);
        next.delete("open-settings");
        setSearchParams(next, { replace: true });
    }, [rawParam, urlSection, searchParams, setSearchParams]);

    const openSettings = useCallback((target: SettingsSection = "account") => {
        setSection(target);
        setOpen(true);
    }, []);

    return { open, setOpen, section, setSection, openSettings };
}
