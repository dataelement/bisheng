import { Button, Input, Segmented, Tag } from "@bisheng/ui";
import { Label } from "@/components/bs-ui/label";
import {
    matchPriceCatalog,
    type ModelPricing,
    type PriceCatalogMatch,
    type PricingCurrency,
} from "@/controllers/API/modelPricing";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
    PRICE_FIELDS,
    type PriceField,
    ZERO_PRICING,
    isValidPrice,
    pricingFromCatalog,
    pricingStatus,
    withPrices,
} from "./modelPricing";

const MATCH_DELAY_MS = 400;
const FIELD_LABELS: Record<PriceField, string> = {
    input: "model.pricing.input",
    cache_read: "model.pricing.cacheRead",
    cache_write: "model.pricing.cacheWrite",
    output: "model.pricing.output",
};

interface ModelPriceFieldsProps {
    /** `config.pricing` of the model; absent until the catalog answers or the admin types. */
    value?: ModelPricing;
    providerType: string;
    modelName: string;
    onChange: (value: ModelPricing) => void;
}

export function ModelPriceFields({ value, providerType, modelName, onChange }: ModelPriceFieldsProps) {
    const { t } = useTranslation("model");
    const controlId = useId();
    const [match, setMatch] = useState<PriceCatalogMatch | null>(null);
    // Prices saved before (they carry a revision) or typed by the admin are never replaced.
    const touched = useRef(false);
    const latest = useRef({ value, onChange });
    latest.current = { value, onChange };
    const shown = value ?? ZERO_PRICING;

    useEffect(() => {
        const name = modelName.trim();
        setMatch(null);
        if (!name || !providerType) return;
        const abort = new AbortController();
        const timer = window.setTimeout(() => {
            matchPriceCatalog(providerType, name, abort.signal)
                .then((result) => {
                    if (abort.signal.aborted) return;
                    setMatch(result);
                    const current = latest.current.value;
                    if (touched.current || current?.revision) return;
                    latest.current.onChange(result.entry ? pricingFromCatalog(result.entry) : { ...ZERO_PRICING });
                })
                .catch(() => {
                    // The prefill is a convenience: without it the admin types prices and the server
                    // still fills catalog or zero prices on save.
                });
        }, MATCH_DELAY_MS);
        return () => {
            window.clearTimeout(timer);
            abort.abort();
        };
    }, [providerType, modelName]);

    const handleEdit = (changes: Partial<ModelPricing>) => {
        touched.current = true;
        onChange(withPrices(value, { ...shown, ...changes }));
    };

    const status = pricingStatus(shown, match);
    const entry = match?.entry;
    const currencyName = (currency: PricingCurrency) =>
        t(currency === "USD" ? "model.pricing.currencyUSD" : "model.pricing.currencyCNY");
    const invalid = PRICE_FIELDS.some((field) => {
        const price = shown[field];
        return field === "cache_write" ? !!price && !isValidPrice(price) : !isValidPrice(price ?? "");
    });

    return (
        <section aria-labelledby={`${controlId}-title`} className="space-y-2 rounded-md border bg-background p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p id={`${controlId}-title`} className="text-sm font-medium">
                    {t("model.pricing.title")}
                </p>
                <Segmented
                    size="small"
                    aria-label={t("model.pricing.currency")}
                    value={shown.currency}
                    onChange={(currency) => handleEdit({ currency: currency as PricingCurrency })}
                    options={[
                        { value: "CNY", label: currencyName("CNY") },
                        { value: "USD", label: currencyName("USD") },
                    ]}
                />
            </div>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                {PRICE_FIELDS.map((field) => {
                    const price = shown[field] ?? "";
                    const fieldInvalid = field === "cache_write" ? !!price && !isValidPrice(price) : !isValidPrice(price);
                    return (
                        <div key={field} className="min-w-0 space-y-1">
                            <Label htmlFor={`${controlId}-${field}`} className="text-xs text-muted-foreground">
                                {t(FIELD_LABELS[field])}
                            </Label>
                            <Input
                                id={`${controlId}-${field}`}
                                size="small"
                                inputMode="decimal"
                                value={price}
                                placeholder={field === "cache_write" ? t("model.pricing.cacheWritePlaceholder") : undefined}
                                status={fieldInvalid ? "error" : undefined}
                                onChange={(event) =>
                                    handleEdit({
                                        [field]: field === "cache_write" && !event.target.value ? null : event.target.value.trim(),
                                    })
                                }
                            />
                        </div>
                    );
                })}
            </div>
            {invalid && (
                <p role="alert" className="text-xs text-destructive">
                    {t("model.pricing.invalid")}
                </p>
            )}
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                {status === "catalog" && entry && (
                    <span>
                        {t("model.pricing.statusCatalog", { vendor: entry.vendor, label: entry.label, date: entry.verified_at })}
                    </span>
                )}
                {status === "review" && entry && (
                    <span className="text-amber-600">{t("model.pricing.statusReview", { label: entry.label })}</span>
                )}
                {status === "edited" && entry && (
                    <>
                        <span>
                            {t("model.pricing.statusEdited", {
                                input: entry.input,
                                cacheRead: entry.cache_read,
                                cacheWrite: entry.cache_write ?? entry.input,
                                output: entry.output,
                                currency: currencyName(entry.currency),
                            })}
                        </span>
                        <Button
                            size="small"
                            variant="link"
                            className="h-auto px-0"
                            onClick={() => {
                                touched.current = true;
                                onChange(withPrices(value, pricingFromCatalog(entry)));
                            }}
                        >
                            {t("model.pricing.restore")}
                        </Button>
                    </>
                )}
                {status === "default" && (
                    <>
                        <Tag size="small" color="warning">
                            {t("model.pricing.defaultTag")}
                        </Tag>
                        <span>{t("model.pricing.statusDefault")}</span>
                    </>
                )}
                {status === "manual" && <span>{t("model.pricing.statusManual")}</span>}
            </div>
            <p className="text-xs text-muted-foreground">{t("model.pricing.help")}</p>
        </section>
    );
}
