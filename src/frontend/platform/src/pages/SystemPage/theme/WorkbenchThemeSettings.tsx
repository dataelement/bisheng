import { Check } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { BrandTickSpinner } from "@/components/bs-icons/loading/BrandTickSpinner";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import {
    BrandConfig,
    WorkbenchTheme,
    getBrandConfigApi,
    saveBrandConfigApi,
} from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { cname } from "@/components/bs-ui/utils";

// Preset accent colors must mirror `.theme-green` / default `--primary` in the
// client app's style.css, so the preview here matches what the workbench renders.
const PRESETS: Array<{ value: WorkbenchTheme; color: string; labelKey: string }> = [
    { value: "blue", color: "#165DFF", labelKey: "theme.workbenchThemeBlue" },
    { value: "green", color: "#187C54", labelKey: "theme.workbenchThemeGreen" },
];

/** Strip linsightAgentName (server ignores it; BrandConfigUpdate omits it). */
function toUpdatePayload(config: BrandConfig, workbenchTheme: WorkbenchTheme) {
    const { linsightAgentName, ...rest } = config;
    return { ...rest, workbenchTheme };
}

/**
 * 工作台主题 — admin picks the end-user app's accent preset (blue | green).
 * Stored in the global brand config; the client applies it before first paint
 * via brand-runtime.js, and its loading spinner follows the resulting --primary.
 */
export default function WorkbenchThemeSettings() {
    const { t } = useTranslation();
    const { toast } = useToast();
    const [config, setConfig] = useState<BrandConfig | null>(null);
    const [selected, setSelected] = useState<WorkbenchTheme>("blue");
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        (async () => {
            const data = await captureAndAlertRequestErrorHoc(getBrandConfigApi());
            if (!data) return;
            setConfig(data);
            setSelected(data.workbenchTheme === "green" ? "green" : "blue");
        })();
    }, []);

    const handleSelect = async (value: WorkbenchTheme) => {
        if (saving || !config || value === selected) return;
        setSaving(true);
        const prev = selected;
        setSelected(value); // optimistic
        const saved = await captureAndAlertRequestErrorHoc(
            saveBrandConfigApi(toUpdatePayload(config, value)),
        );
        setSaving(false);
        if (!saved) {
            setSelected(prev); // rollback
            return;
        }
        setConfig(saved);
        toast({ title: t("prompt"), variant: "success", description: t("theme.workbenchThemeSaved") });
    };

    if (!config) {
        return (
            <div className="flex h-40 items-center justify-center border-t bg-accent">
                <LoadingIcon className="size-8" />
            </div>
        );
    }

    return (
        <div className="border-t bg-accent p-6">
            <p className="mb-1 text-lg">{t("theme.workbenchTheme")}</p>
            <p className="mb-6 text-sm text-muted-foreground">{t("theme.workbenchThemeDesc")}</p>

            <div className="flex flex-wrap gap-4">
                {PRESETS.map((preset) => {
                    const active = selected === preset.value;
                    return (
                        <button
                            key={preset.value}
                            type="button"
                            disabled={saving}
                            onClick={() => handleSelect(preset.value)}
                            className={cname(
                                "relative flex w-44 flex-col items-center gap-3 rounded-xl border bg-card p-5 transition-colors",
                                active ? "border-primary ring-1 ring-primary" : "border-border hover:border-primary/50",
                                saving && "cursor-not-allowed opacity-70",
                            )}
                        >
                            {active && (
                                <span className="absolute right-2 top-2 flex size-5 items-center justify-center rounded-full bg-primary text-primary-foreground">
                                    <Check className="size-3.5" />
                                </span>
                            )}
                            {/* Preview the workbench spinner tinted with the preset color. */}
                            <span className="flex size-12 items-center justify-center" style={{ color: preset.color }}>
                                <BrandTickSpinner className="size-12" />
                            </span>
                            <div className="flex items-center gap-2">
                                <span className="inline-block size-3.5 rounded-full" style={{ backgroundColor: preset.color }} />
                                <span className="text-sm">{t(preset.labelKey)}</span>
                            </div>
                        </button>
                    );
                })}
            </div>
        </div>
    );
}
