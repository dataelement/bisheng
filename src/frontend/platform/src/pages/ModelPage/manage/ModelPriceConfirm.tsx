import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import type { ModelPricing } from "@/controllers/API/modelPricing";
import i18next from "i18next";
import { useTranslation } from "react-i18next";
import { PRICE_FIELDS, PRICE_FIELD_LABELS, type PriceField } from "./modelPricing";

export interface PriceChange {
    /** Model shown above its prices when one save changes several models. */
    name?: string;
    /** Saved price; absent when the model had none yet. */
    before?: ModelPricing;
    after: ModelPricing;
}

const shownPrice = (pricing: ModelPricing, field: PriceField) => {
    const price = field === "cache_write" && !pricing.cache_write ? pricing.input : pricing[field];
    return `${pricing.currency === "USD" ? "$" : "¥"}${price}`;
};

// The confirm description renders inside a <p>, so the table is built from spans.
function PriceChangeList({ changes }: { changes: PriceChange[] }) {
    const { t } = useTranslation("model");
    const row = "grid grid-cols-[1fr_6rem_6rem] gap-2 border-b py-1";
    return (
        <span className="block space-y-3">
            {changes.map((change, index) => (
                <span key={index} className="block">
                    {change.name && <span className="block font-medium">{change.name}</span>}
                    <span className={`${row} text-xs text-muted-foreground`}>
                        <span />
                        <span>{t("model.pricing.before")}</span>
                        <span>{t("model.pricing.after")}</span>
                    </span>
                    {PRICE_FIELDS.map((field) => {
                        const before = change.before ? shownPrice(change.before, field) : "—";
                        const after = shownPrice(change.after, field);
                        return (
                            <span key={field} className={row}>
                                <span>{t(PRICE_FIELD_LABELS[field])}</span>
                                <span>{before}</span>
                                <span className={before === after ? undefined : "font-medium text-primary"}>{after}</span>
                            </span>
                        );
                    })}
                </span>
            ))}
            <span className="block text-xs text-muted-foreground">{t("model.pricing.confirmHelp")}</span>
        </span>
    );
}

/** Ask before saving changed prices; resolves true once the administrator confirms. */
export function confirmPriceChanges(changes: PriceChange[]): Promise<boolean> {
    if (!changes.length) return Promise.resolve(true);
    const t = (key: string) => i18next.t(key, { ns: "model" });
    return new Promise((resolve) =>
        bsConfirm({
            // Not destructive: the price can be changed back, so the primary tone.
            variant: "default",
            title: t("model.pricing.confirmTitle"),
            desc: <PriceChangeList changes={changes} />,
            okTxt: t("model.pricing.confirmOk"),
            canelTxt: t("model.pricing.confirmCancel"),
            onOk: (close) => {
                resolve(true);
                close();
            },
            // Also runs after onOk; the promise has settled by then.
            onClose: () => resolve(false),
        }),
    );
}
