import { Button } from "@/components/bs-ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
} from "@/components/bs-ui/select";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import type { BrandAsset, BrandAssetCategory, BrandAssetOption } from "@/controllers/API";
import { deleteBrandAssetApi, uploadBrandAssetApi } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { withBrandBaseUrl } from "@/utils/brand";
import { Check, Eye, ImageIcon, Link, Loader2, Trash2, Upload } from "lucide-react";
import { ChangeEvent, MouseEvent, PointerEvent, ReactNode, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { BRAND_ASSET_ACCEPT } from "./brandTypes";

const EMPTY_DEFAULT_VALUE = "__brand_empty_default__";

interface BrandAssetUploadProps {
    label: string;
    spec: string;
    value?: BrandAsset | null;
    fallbackUrl?: string;
    category?: BrandAssetCategory;
    options?: BrandAssetOption[];
    allowUrlOption?: boolean;
    emptyPreview?: ReactNode;
    previewActive?: boolean;
    onChange: (asset: BrandAsset) => void;
    onPreview?: () => void;
    onUploaded?: (asset: BrandAsset) => void;
    onDeleted?: (deletedAsset: BrandAssetOption, fallbackAsset: BrandAsset) => void;
    onUrlAdded?: (asset: BrandAsset) => void;
}

const getAssetValue = (asset?: BrandAsset | null) => (
    asset?.relative_path || asset?.url || ""
);

const getOptionValue = (asset?: BrandAssetOption | BrandAsset | null) => (
    getAssetValue(asset) || EMPTY_DEFAULT_VALUE
);

const getFileName = (asset?: BrandAsset | null) => {
    if (asset?.file_name) return asset.file_name;
    const source = asset?.relative_path || asset?.url || "";
    if (!source || source.startsWith("data:")) return "";
    const cleanSource = source.split("?")[0];
    return cleanSource.split("/").pop() || cleanSource;
};

const isValidAssetUrl = (value: string) => {
    const trimmed = value.trim();
    return /^https?:\/\/[^\s<>]+$/i.test(trimmed);
};

function AssetOptionContent({
    option,
    label,
    selected = false,
    deleting = false,
    emptyPreview,
    onDelete,
}: {
    option: BrandAssetOption;
    label: string;
    selected?: boolean;
    deleting?: boolean;
    emptyPreview?: ReactNode;
    onDelete?: (option: BrandAssetOption) => void;
}) {
    const { t } = useTranslation();
    const pointerDeleteTriggeredRef = useRef(false);
    const previewUrl = withBrandBaseUrl(option.url);
    const canDelete = !option.is_default && !!onDelete && (!!option.relative_path || !!option.url);

    const handleDeletePointerDown = (event: PointerEvent<HTMLButtonElement>) => {
        event.preventDefault();
        event.stopPropagation();
        if (event.button !== 0 || deleting) return;
        pointerDeleteTriggeredRef.current = true;
        onDelete?.(option);
        window.setTimeout(() => {
            pointerDeleteTriggeredRef.current = false;
        }, 300);
    };

    const handleDeleteMouseDown = (event: MouseEvent<HTMLButtonElement>) => {
        event.preventDefault();
        event.stopPropagation();
    };

    const handleDeleteClick = (event: MouseEvent<HTMLButtonElement>) => {
        event.preventDefault();
        event.stopPropagation();
        if (pointerDeleteTriggeredRef.current || deleting) return;
        onDelete?.(option);
    };

    return (
        <div className="flex min-w-0 flex-1 items-center gap-2">
            <div className="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded border bg-muted">
                {previewUrl ? (
                    <img src={previewUrl} alt={label} className="max-h-full max-w-full object-contain" />
                ) : emptyPreview ? (
                    emptyPreview
                ) : (
                    <ImageIcon className="size-4 text-muted-foreground" />
                )}
            </div>
            <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-2">
                    <span className="truncate text-sm text-foreground">{getFileName(option)}</span>
                    {option.is_default && (
                        <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[11px] text-primary">
                            {t("theme.brandDefaultAsset")}
                        </span>
                    )}
                </div>
            </div>
            {selected && <Check className="size-4 shrink-0 text-primary" />}
            {canDelete && (
                <button
                    type="button"
                    className="flex size-7 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-destructive/10 hover:text-destructive disabled:cursor-not-allowed disabled:opacity-50"
                    aria-label={t("theme.brandDeleteAsset")}
                    title={t("theme.brandDeleteAsset")}
                    disabled={deleting}
                    onPointerDown={handleDeletePointerDown}
                    onMouseDown={handleDeleteMouseDown}
                    onClick={handleDeleteClick}
                >
                    {deleting ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                </button>
            )}
        </div>
    );
}

export default function BrandAssetUpload({
    label,
    spec,
    value,
    fallbackUrl = "",
    category,
    options = [],
    allowUrlOption = false,
    emptyPreview,
    previewActive = false,
    onChange,
    onPreview,
    onUploaded,
    onDeleted,
    onUrlAdded,
}: BrandAssetUploadProps) {
    const { t } = useTranslation();
    const { toast } = useToast();
    const inputRef = useRef<HTMLInputElement>(null);
    const [uploading, setUploading] = useState(false);
    const [deletingValue, setDeletingValue] = useState("");
    const [urlDialogOpen, setUrlDialogOpen] = useState(false);
    const [urlValue, setUrlValue] = useState("");
    const selectable = !!category;
    const rawSelectedValue = getAssetValue(value);
    const selectedValue = selectable ? rawSelectedValue || EMPTY_DEFAULT_VALUE : rawSelectedValue;
    const effectiveOptions = useMemo(() => {
        if (!selectable || !selectedValue || options.some((option) => getOptionValue(option) === selectedValue)) {
            return options;
        }

        return [
            {
                url: value?.url || fallbackUrl,
                relative_path: value?.relative_path || "",
                file_name: getFileName(value),
            },
            ...options,
        ];
    }, [fallbackUrl, options, selectable, selectedValue, value]);
    const selectedOption = effectiveOptions.find((option) => getOptionValue(option) === selectedValue);
    const previewUrl = withBrandBaseUrl(selectedOption?.url || value?.url || fallbackUrl);

    const handlePickFile = () => {
        inputRef.current?.click();
    };

    const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        event.target.value = "";
        if (!file) return;

        const formData = new FormData();
        formData.append("file", file);
        if (category) {
            formData.append("category", category);
        }
        setUploading(true);
        const uploaded = await captureAndAlertRequestErrorHoc(uploadBrandAssetApi(formData));
        setUploading(false);
        if (!uploaded) return;

        onChange(uploaded);
        onUploaded?.(uploaded);
        toast({
            title: t("prompt"),
            variant: "success",
            description: t("theme.brandAssetUploadSuccess"),
        });
    };

    const handleAssetSelect = (assetValue: string) => {
        const selected = effectiveOptions.find((option) => getOptionValue(option) === assetValue);
        if (!selected) return;
        onChange({
            url: selected.url,
            relative_path: selected.relative_path || "",
            file_name: selected.file_name || "",
        });
    };

    const getFallbackAsset = (): BrandAsset => {
        const defaultOption = effectiveOptions.find((option) => option.is_default);
        return {
            url: defaultOption?.url || fallbackUrl,
            relative_path: defaultOption?.relative_path || "",
            file_name: defaultOption?.file_name || getFileName(defaultOption) || getFileName({ url: fallbackUrl }),
        };
    };

    const handleAssetDelete = async (option: BrandAssetOption) => {
        if (option.is_default) return;

        const optionValue = getOptionValue(option);
        if (!option.relative_path) {
            const fallbackAsset = getFallbackAsset();
            if (optionValue === selectedValue) {
                onChange(fallbackAsset);
            }
            onDeleted?.(option, fallbackAsset);
            toast({
                title: t("prompt"),
                variant: "success",
                description: t("theme.brandAssetDeleteSuccess"),
            });
            return;
        }

        if (!category) return;
        setDeletingValue(optionValue);
        const defaultAsset = await captureAndAlertRequestErrorHoc(
            deleteBrandAssetApi(category, option.relative_path)
        );
        setDeletingValue("");
        if (!defaultAsset) return;

        const fallbackAsset: BrandAsset = {
            url: defaultAsset.url || fallbackUrl,
            relative_path: defaultAsset.relative_path || "",
            file_name: defaultAsset.file_name || getFileName(defaultAsset),
        };

        if (optionValue === selectedValue) {
            onChange(fallbackAsset);
        }
        onDeleted?.(option, fallbackAsset);
        toast({
            title: t("prompt"),
            variant: "success",
            description: t("theme.brandAssetDeleteSuccess"),
        });
    };

    const handleOpenUrlDialog = () => {
        setUrlValue("");
        setUrlDialogOpen(true);
    };

    const handleUrlConfirm = () => {
        const nextUrl = urlValue.trim();
        if (!isValidAssetUrl(nextUrl)) {
            toast({
                title: t("prompt"),
                variant: "warning",
                description: t("theme.brandAssetUrlInvalid"),
            });
            return;
        }

        const urlAsset: BrandAsset = {
            url: nextUrl,
            relative_path: "",
            file_name: getFileName({ url: nextUrl }) || t("theme.brandUrlAssetName"),
        };
        onChange(urlAsset);
        onUrlAdded?.(urlAsset);
        setUrlDialogOpen(false);
        toast({
            title: t("prompt"),
            variant: "success",
            description: t("theme.brandAssetUrlAddSuccess"),
        });
    };

    const handleUrlChange = (event: ChangeEvent<HTMLInputElement>) => {
        onChange({
            url: event.target.value,
            relative_path: "",
            file_name: value?.file_name || "",
        });
    };

    return (
        <>
            <div className="grid grid-cols-1 gap-4 rounded-md border border-border bg-background px-4 py-3 sm:grid-cols-[112px_minmax(0,1fr)]">
            <div className="flex h-[88px] w-[112px] items-center justify-center overflow-hidden rounded border border-dashed bg-muted">
                {previewUrl ? (
                    <img src={previewUrl} alt={label} className="max-h-full max-w-full object-contain" />
                ) : emptyPreview ? (
                    emptyPreview
                ) : (
                    <ImageIcon className="size-8 text-muted-foreground" />
                )}
            </div>
            <div className="min-w-0 space-y-3">
                <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-foreground">{label}</p>
                        <p className="mt-1 text-xs text-muted-foreground">{spec}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                        {onPreview && (
                            <Button
                                type="button"
                                size="sm"
                                variant={previewActive ? "default" : "outline"}
                                onClick={onPreview}
                            >
                                <Eye className="mr-1 size-4" />
                                {t("theme.brandPreviewButton")}
                            </Button>
                        )}
                        {allowUrlOption && (
                            <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                onClick={handleOpenUrlDialog}
                            >
                                <Link className="mr-1 size-4" />
                                {t("theme.brandPasteUrl")}
                            </Button>
                        )}
                        <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={uploading}
                            onClick={handlePickFile}
                        >
                            <Upload className="mr-1 size-4" />
                            {uploading ? t("theme.brandUploading") : t("theme.brandUpload")}
                        </Button>
                    </div>
                </div>
                {selectable ? (
                    <Select value={selectedValue} onValueChange={handleAssetSelect}>
                        <SelectTrigger className="h-11 bg-background">
                            {selectedOption ? (
                                <AssetOptionContent option={selectedOption} label={label} emptyPreview={emptyPreview} />
                            ) : (
                                <span className="text-sm text-muted-foreground">
                                    {t("theme.brandSelectAssetPlaceholder")}
                                </span>
                            )}
                        </SelectTrigger>
                        <SelectContent className="w-[var(--radix-select-trigger-width)]">
                            {effectiveOptions.map((option) => {
                                const optionValue = getOptionValue(option);
                                return (
                                    <SelectItem
                                        key={optionValue}
                                        value={optionValue}
                                        textValue={getFileName(option)}
                                        customContent
                                        showIcon={false}
                                        className="pr-2"
                                    >
                                        <AssetOptionContent
                                            option={option}
                                            label={label}
                                            selected={optionValue === selectedValue}
                                            deleting={deletingValue === optionValue}
                                            emptyPreview={emptyPreview}
                                            onDelete={handleAssetDelete}
                                        />
                                    </SelectItem>
                                );
                            })}
                        </SelectContent>
                    </Select>
                ) : (
                    <Input
                        value={value?.url || ""}
                        placeholder={t("theme.brandAssetUrlPlaceholder")}
                        onChange={handleUrlChange}
                    />
                )}
            </div>
            <input
                ref={inputRef}
                type="file"
                className="hidden"
                accept={BRAND_ASSET_ACCEPT}
                onChange={handleFileChange}
            />
            </div>
            <Dialog open={urlDialogOpen} onOpenChange={setUrlDialogOpen}>
                <DialogContent className="sm:max-w-[520px]">
                    <DialogHeader>
                        <DialogTitle>{t("theme.brandUrlDialogTitle")}</DialogTitle>
                        <DialogDescription>{t("theme.brandUrlDialogDescription")}</DialogDescription>
                    </DialogHeader>
                    <Input
                        value={urlValue}
                        placeholder={t("theme.brandAssetUrlPlaceholder")}
                        onChange={(event) => setUrlValue(event.target.value)}
                        onKeyDown={(event) => {
                            if (event.key === "Enter") {
                                handleUrlConfirm();
                            }
                        }}
                    />
                    <DialogFooter>
                        <Button type="button" variant="outline" onClick={() => setUrlDialogOpen(false)}>
                            {t("theme.brandUrlDialogCancel")}
                        </Button>
                        <Button type="button" onClick={handleUrlConfirm}>
                            {t("theme.brandUrlDialogConfirm")}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    );
}
