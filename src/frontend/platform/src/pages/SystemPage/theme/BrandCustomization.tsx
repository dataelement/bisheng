import { Button, LoadButton } from "@/components/bs-ui/button";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/bs-ui/select";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { darkContext } from "@/contexts/darkContext";
import type { BrandAsset, BrandAssetOption, BrandConfig, BrandText } from "@/controllers/API";
import { getBrandAssetOptionsApi, getBrandConfigApi, saveBrandConfigApi } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { withBrandBaseUrl } from "@/utils/brand";
import { LoadingIcon } from "@/components/bs-icons/loading";
import BuiltinLoadingIcon from "@/components/bs-icons/loading/Loading.svg?react";
import { Eye, RefreshCw, Save } from "lucide-react";
import { ChangeEvent, useContext, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import BrandAssetUpload from "./BrandAssetUpload";
import BrandPreviewPanel from "./BrandPreviewPanel";
import { BrandAssetKey, BrandPreviewTarget, BrandTextKey, buildDefaultAssetOptions, cloneBrandConfig, DEFAULT_BRAND_CONFIG } from "./brandTypes";

const ASSET_ROWS: Array<{
    key: BrandAssetKey;
    labelKey: string;
    specKey: string;
}> = [
    { key: "favicon", labelKey: "theme.brandFavicon", specKey: "theme.brandFaviconSpec" },
    { key: "loginHeroLight", labelKey: "theme.brandLoginHeroLight", specKey: "theme.brandLoginHeroSpec" },
    { key: "loginHeroDark", labelKey: "theme.brandLoginHeroDark", specKey: "theme.brandLoginHeroDarkSpec" },
    { key: "headerLogoLight", labelKey: "theme.brandHeaderLogoLight", specKey: "theme.brandHeaderLogoSpec" },
    { key: "headerLogoDark", labelKey: "theme.brandHeaderLogoDark", specKey: "theme.brandHeaderLogoDarkSpec" },
];

const TEXT_ROWS: Array<{
    key: BrandTextKey;
    labelKey: string;
    descKey: string;
}> = [
    {
        key: "brandName",
        labelKey: "theme.brandSystemName",
        descKey: "theme.brandSystemNameDesc",
    },
];

const getBrandTitle = (brandName?: BrandText) => {
    const language = localStorage.getItem("i18nextLng") || navigator.language || "en-US";
    return language.toLowerCase().startsWith("zh")
        ? (brandName?.zh || brandName?.en || "")
        : (brandName?.en || brandName?.zh || "");
};

const hasInvalidBrandText = (brandName: BrandText) => (
    brandName.zh.includes("<")
    || brandName.zh.includes(">")
    || brandName.en.includes("<")
    || brandName.en.includes(">")
);

const omitLinsightAgentName = (config: BrandConfig) => {
    const payload = { ...config } as Partial<BrandConfig>;
    delete payload.linsightAgentName;
    return payload as Omit<BrandConfig, "linsightAgentName">;
};

function applyRuntimeBrandConfig(config: BrandConfig) {
    const loadingIcon = config.URLLoadingIcon || config.loading?.icon?.url || "";
    window.BRAND_CONFIG = {
        ...window.BRAND_CONFIG,
        ...omitLinsightAgentName(config),
        loadingIcon,
        URLLoadingIcon: loadingIcon,
        loadingAnimation: config.loading?.animation || "",
    };
    const title = getBrandTitle(config.brandName);
    if (title) {
        document.title = title;
    }
    const favicon = config.assets?.favicon?.url;
    if (favicon) {
        const link = document.querySelector("link[rel*='icon']") || document.createElement("link");
        link.setAttribute("rel", "icon");
        link.setAttribute("href", withBrandBaseUrl(favicon));
        document.head.appendChild(link);
    }
}

function normalizeForSave(config: BrandConfig) {
    const next = cloneBrandConfig(config);
    const loadingIconUrl = next.loading?.icon?.url || next.URLLoadingIcon || "";
    next.URLLoadingIcon = loadingIconUrl;
    next.loading.iconOptions = normalizeLoadingUrlOptions(
        next.loading?.icon?.url && !next.loading.icon.relative_path
            ? upsertAssetOption(next.loading.iconOptions, next.loading.icon)
            : next.loading.iconOptions
    );
    if (!loadingIconUrl) {
        next.loading.icon = null;
    }
    return omitLinsightAgentName(next);
}

const getAssetValue = (asset?: BrandAsset | null) => (
    asset?.relative_path || asset?.url || ""
);

const DEFAULT_OPTION_VALUE = "__default__";

const mergeAssetOptions = (options: BrandAssetOption[]) => {
    const seen = new Set<string>();
    return options.filter((option) => {
        const value = getAssetValue(option) || DEFAULT_OPTION_VALUE;
        if (seen.has(value)) return false;
        seen.add(value);
        return true;
    });
};

const upsertAssetOption = (options: BrandAsset[] = [], asset: BrandAsset) => {
    const assetValue = getAssetValue(asset);
    if (!assetValue) return options;
    return [
        {
            url: asset.url || "",
            relative_path: asset.relative_path || "",
            file_name: asset.file_name || "",
        },
        ...options.filter((option) => getAssetValue(option) !== assetValue),
    ];
};

const normalizeLoadingUrlOptions = (options: BrandAsset[] = []) => {
    const seen = new Set<string>();
    return options.filter((option) => {
        if (!option.url || option.relative_path) return false;
        const value = getAssetValue(option);
        if (!value || seen.has(value)) return false;
        seen.add(value);
        return true;
    }).map((option) => ({
        url: option.url,
        relative_path: "",
        file_name: option.file_name || "",
    }));
};

function BrandTextField({
    label,
    description,
    value,
    previewActive,
    onChange,
    onPreview,
}: {
    label: string;
    description: string;
    value: BrandText;
    previewActive: boolean;
    onChange: (next: BrandText) => void;
    onPreview: () => void;
}) {
    const { t } = useTranslation();

    const handleChange = (lang: keyof BrandText) => (event: ChangeEvent<HTMLInputElement>) => {
        onChange({
            ...value,
            [lang]: event.target.value,
        });
    };

    return (
        <div className="grid grid-cols-1 items-center gap-3 lg:grid-cols-[180px_minmax(0,1fr)_minmax(0,1fr)_72px]">
            <div className="space-y-1">
                <Label className="text-sm text-foreground">{label}</Label>
                <p className="text-xs leading-5 text-muted-foreground">{description}</p>
            </div>
            <Input
                value={value.zh}
                maxLength={20}
                placeholder={t("theme.brandZhPlaceholder")}
                onChange={handleChange("zh")}
            />
            <Input
                value={value.en}
                maxLength={20}
                placeholder={t("theme.brandEnPlaceholder")}
                onChange={handleChange("en")}
            />
            <Button
                type="button"
                size="sm"
                variant={previewActive ? "default" : "outline"}
                className="w-fit justify-self-start"
                onClick={onPreview}
            >
                <Eye className="mr-1 size-3.5" />
                {t("theme.brandPreviewButton")}
            </Button>
        </div>
    );
}

export default function BrandCustomization() {
    const { t } = useTranslation();
    const { toast } = useToast();
    const { dark } = useContext(darkContext);
    const [config, setConfig] = useState<BrandConfig>(() => cloneBrandConfig(DEFAULT_BRAND_CONFIG));
    const [assetOptions, setAssetOptions] = useState<Record<BrandAssetKey, BrandAssetOption[]>>(
        () => buildDefaultAssetOptions()
    );
    const [loadingIconUploadOptions, setLoadingIconUploadOptions] = useState<BrandAssetOption[]>([]);
    const [previewTarget, setPreviewTarget] = useState<BrandPreviewTarget | null>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        let mounted = true;

        const loadBrandData = async () => {
            const [configData, optionEntries, loadingIconOptions] = await Promise.all([
                captureAndAlertRequestErrorHoc(getBrandConfigApi()),
                Promise.all(ASSET_ROWS.map(async ({ key }) => ({
                    key,
                    options: await captureAndAlertRequestErrorHoc(getBrandAssetOptionsApi(key)),
                }))),
                captureAndAlertRequestErrorHoc(getBrandAssetOptionsApi("loadingIcon")),
            ]);

            if (!mounted) return;

            if (configData) {
                setConfig(configData);
            }

            setAssetOptions((current) => {
                const next = { ...current };
                optionEntries.forEach(({ key, options }) => {
                    if (options) {
                        next[key] = options;
                    }
                });
                return next;
            });
            if (loadingIconOptions) {
                setLoadingIconUploadOptions(loadingIconOptions.filter((option) => !option.is_default));
            }
            setLoading(false);
        };

        loadBrandData();

        return () => {
            mounted = false;
        };
    }, []);

    const handleAssetUploaded = (key: BrandAssetKey, asset: BrandAsset) => {
        setAssetOptions((current) => {
            const uploadedOption: BrandAssetOption = { ...asset, is_default: false };
            const uploadedValue = getAssetValue(uploadedOption);
            return {
                ...current,
                [key]: [
                    uploadedOption,
                    ...(current[key] || []).filter((option) => getAssetValue(option) !== uploadedValue),
                ],
            };
        });
    };

    const handleAssetDeleted = (
        key: BrandAssetKey,
        deletedAsset: BrandAssetOption,
        fallbackAsset: BrandAsset,
        deletedWasSelected: boolean,
    ) => {
        const deletedValue = getAssetValue(deletedAsset);
        setAssetOptions((current) => ({
            ...current,
            [key]: (current[key] || []).filter((option) => getAssetValue(option) !== deletedValue),
        }));
        setConfig((current) => {
            if (!deletedWasSelected || getAssetValue(current.assets[key]) !== deletedValue) {
                return current;
            }
            return {
                ...current,
                assets: {
                    ...current.assets,
                    [key]: fallbackAsset,
                },
            };
        });
    };

    const loadingIconAsset = useMemo<BrandAsset>(() => (
        config.loading.icon || {
            url: config.URLLoadingIcon || DEFAULT_BRAND_CONFIG.URLLoadingIcon || "",
            relative_path: "",
            file_name: config.URLLoadingIcon ? "" : t("theme.brandDefaultLoadingIcon"),
        }
    ), [config.URLLoadingIcon, config.loading.icon, t]);
    const defaultLoadingAsset = useMemo<BrandAsset>(() => DEFAULT_BRAND_CONFIG.loading.icon || {
        url: DEFAULT_BRAND_CONFIG.URLLoadingIcon || "",
        relative_path: "",
        file_name: "default-loading-icon",
    }, []);
    const loadingIconOptions = useMemo<BrandAssetOption[]>(() => (
        mergeAssetOptions([
            // 1. Built-in <Loading> SVG component — empty url renders the emptyPreview component. Default.
            {
                ...defaultLoadingAsset,
                file_name: t("theme.brandDefaultLoadingIcon"),
                is_default: true,
            },
            // 2. Built-in static loading image preset (the classic /assets/bisheng/loading.svg). Selectable, not default.
            {
                url: "/assets/bisheng/loading.svg",
                relative_path: "",
                file_name: t("theme.brandStaticLoadingIcon"),
                is_default: false,
            },
            ...loadingIconUploadOptions.map((option) => ({ ...option, is_default: false })),
            ...(config.loading.iconOptions || []).map((option) => ({ ...option, is_default: false })),
        ])
    ), [config.loading.iconOptions, defaultLoadingAsset, loadingIconUploadOptions, t]);
    const handleTextChange = (key: BrandTextKey, value: BrandText) => {
        setConfig((current) => ({
            ...current,
            [key]: value,
        }));
    };

    const handleAssetChange = (key: BrandAssetKey, asset: BrandAsset) => {
        setConfig((current) => ({
            ...current,
            assets: {
                ...current.assets,
                [key]: asset,
            },
        }));
    };

    const handleLoadingIconChange = (asset: BrandAsset) => {
        setConfig((current) => ({
            ...current,
            URLLoadingIcon: asset.url,
            loading: {
                ...current.loading,
                icon: asset.url ? asset : null,
                iconOptions: asset.url && !asset.relative_path
                    ? upsertAssetOption(current.loading.iconOptions, asset)
                    : current.loading.iconOptions,
            },
        }));
    };

    const handleLoadingIconUploaded = (asset: BrandAsset) => {
        setLoadingIconUploadOptions((current) => {
            const uploadedOption: BrandAssetOption = { ...asset, is_default: false };
            const uploadedValue = getAssetValue(uploadedOption);
            return [
                uploadedOption,
                ...current.filter((option) => getAssetValue(option) !== uploadedValue),
            ];
        });
    };

    const handleLoadingUrlAdded = (asset: BrandAsset) => {
        setConfig((current) => ({
            ...current,
            loading: {
                ...current.loading,
                iconOptions: upsertAssetOption(current.loading.iconOptions, asset),
            },
        }));
    };

    const handleLoadingIconDeleted = (
        deletedAsset: BrandAssetOption,
        fallbackAsset: BrandAsset,
        deletedWasSelected: boolean,
    ) => {
        const deletedValue = getAssetValue(deletedAsset);
        if (deletedAsset.relative_path) {
            setLoadingIconUploadOptions((current) => (
                current.filter((option) => getAssetValue(option) !== deletedValue)
            ));
        }

        setConfig((current) => {
            const currentValue = getAssetValue(current.loading.icon) || current.URLLoadingIcon || "";
            const shouldResetCurrent = deletedWasSelected && currentValue === deletedValue;
            return {
                ...current,
                URLLoadingIcon: shouldResetCurrent ? fallbackAsset.url : current.URLLoadingIcon,
                loading: {
                    ...current.loading,
                    icon: shouldResetCurrent ? (fallbackAsset.url ? fallbackAsset : null) : current.loading.icon,
                    iconOptions: (current.loading.iconOptions || []).filter((option) => (
                        getAssetValue(option) !== deletedValue
                    )),
                },
            };
        });
    };

    const handleAnimationChange = (animation: BrandConfig["loading"]["animation"]) => {
        setConfig((current) => ({
            ...current,
            loading: {
                ...current.loading,
                animation,
            },
        }));
    };

    const handleReset = () => {
        setConfig(cloneBrandConfig(DEFAULT_BRAND_CONFIG));
    };

    const handleSave = async () => {
        if (hasInvalidBrandText(config.brandName)) {
            toast({
                title: t("prompt"),
                variant: "warning",
                description: t("theme.brandNameInvalidCharacters"),
            });
            return;
        }

        setSaving(true);
        const saved = await captureAndAlertRequestErrorHoc(saveBrandConfigApi(normalizeForSave(config)));
        setSaving(false);
        if (!saved) return;

        setConfig(saved);
        applyRuntimeBrandConfig(saved);
        toast({
            title: t("prompt"),
            variant: "success",
            description: t("theme.brandSaveSuccess"),
        });
    };

    return (
        <div className="h-full min-h-0 overflow-y-auto border-t bg-accent">
            {loading ? (
                // Wait for the API before rendering, so the BISHENG defaults
                // don't flash in before the saved config arrives.
                <div className="flex h-full items-center justify-center">
                    <LoadingIcon className="size-7" />
                </div>
            ) : (
            <div className="mx-auto grid max-w-[1480px] grid-cols-1 gap-6 px-6 py-5 xl:grid-cols-[minmax(0,1fr)_520px]">
                <div className="min-w-0 space-y-6">
                    <div className="flex items-center justify-between gap-3">
                        <h2 className="text-lg font-medium">{t("theme.brandCustomization")}</h2>
                        <div className="flex items-center gap-2">
                            <Button type="button" variant="outline" onClick={handleReset} disabled={loading || saving}>
                                <RefreshCw className="mr-1 size-4" />
                                {t("theme.brandResetDefault")}
                            </Button>
                            <LoadButton type="button" loading={saving} disabled={loading} onClick={handleSave}>
                                <Save className="mr-1 size-4" />
                                {t("theme.brandSave")}
                            </LoadButton>
                        </div>
                    </div>

                    <section className="space-y-3 rounded-md border border-border bg-background p-4">
                        <h3 className="text-base font-medium">{t("theme.brandTextSection")}</h3>
                        <div className="space-y-3">
                            <div className="hidden grid-cols-[180px_minmax(0,1fr)_minmax(0,1fr)_72px] items-center gap-3 lg:grid">
                                <span />
                                <span className="text-xs font-medium text-muted-foreground">{t("theme.brandChineseColumn")}</span>
                                <span className="text-xs font-medium text-muted-foreground">{t("theme.brandEnglishColumn")}</span>
                                <span />
                            </div>
                            {TEXT_ROWS.map(({ key, labelKey, descKey }) => (
                                <BrandTextField
                                    key={key}
                                    label={t(labelKey)}
                                    description={t(descKey)}
                                    value={config[key]}
                                    previewActive={previewTarget === key}
                                    onChange={(value) => handleTextChange(key, value)}
                                    onPreview={() => setPreviewTarget(key)}
                                />
                            ))}
                        </div>
                    </section>

                    <section className="space-y-3">
                        <h3 className="text-base font-medium">{t("theme.brandAssetsSection")}</h3>
                        <div className="grid gap-3">
                            {ASSET_ROWS.map(({ key, labelKey, specKey }) => (
                                <BrandAssetUpload
                                    key={key}
                                    label={t(labelKey)}
                                    spec={t(specKey)}
                                    value={config.assets[key]}
                                    fallbackUrl={DEFAULT_BRAND_CONFIG.assets[key].url}
                                    category={key}
                                    options={assetOptions[key]}
                                    previewActive={previewTarget === key}
                                    onChange={(asset) => handleAssetChange(key, asset)}
                                    onPreview={() => setPreviewTarget(key)}
                                    onUploaded={(asset) => handleAssetUploaded(key, asset)}
                                    onDeleted={(deletedAsset, fallbackAsset, deletedWasSelected) => (
                                        handleAssetDeleted(key, deletedAsset, fallbackAsset, deletedWasSelected)
                                    )}
                                />
                            ))}
                        </div>
                    </section>

                    <section className="space-y-3 rounded-md border border-border bg-background p-4">
                        <h3 className="text-base font-medium">{t("theme.brandLoadingSection")}</h3>
                        <BrandAssetUpload
                            label={t("theme.brandLoadingIcon")}
                            spec={t("theme.brandLoadingIconSpec")}
                            value={loadingIconAsset}
                            category="loadingIcon"
                            options={loadingIconOptions}
                            allowUrlOption
                            emptyPreview={<BuiltinLoadingIcon className="size-6 text-primary" />}
                            previewActive={previewTarget === "loadingIcon"}
                            onChange={handleLoadingIconChange}
                            onPreview={() => setPreviewTarget("loadingIcon")}
                            onUploaded={handleLoadingIconUploaded}
                            onDeleted={handleLoadingIconDeleted}
                            onUrlAdded={handleLoadingUrlAdded}
                        />
                        <div className="grid grid-cols-1 items-center gap-3 sm:grid-cols-[140px_minmax(0,240px)_auto]">
                            <Label>{t("theme.brandLoadingAnimation")}</Label>
                            <Select value={config.loading.animation || "none"} onValueChange={(value) => handleAnimationChange(value === "none" ? "" : value as BrandConfig["loading"]["animation"])}>
                                <SelectTrigger>
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="none">{t("theme.brandAnimationNone")}</SelectItem>
                                    <SelectItem value="animate-spin">{t("theme.brandAnimationSpin")}</SelectItem>
                                    <SelectItem value="animate-pulse">{t("theme.brandAnimationPulse")}</SelectItem>
                                    <SelectItem value="animate-bounce">{t("theme.brandAnimationBounce")}</SelectItem>
                                </SelectContent>
                            </Select>
                            <Button
                                type="button"
                                size="sm"
                                variant={previewTarget === "loadingAnimation" ? "default" : "outline"}
                                className="w-fit"
                                onClick={() => setPreviewTarget("loadingAnimation")}
                            >
                                <Eye className="mr-1 size-4" />
                                {t("theme.brandPreviewButton")}
                            </Button>
                        </div>
                    </section>
                </div>

                <BrandPreviewPanel config={config} target={previewTarget} dark={Boolean(dark)} />
            </div>
            )}
        </div>
    );
}
