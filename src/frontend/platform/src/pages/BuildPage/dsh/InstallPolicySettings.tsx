import { Switch } from "@/components/bs-ui/switch";
import { toast } from "@/components/bs-ui/toast/use-toast";
import { getMarketInstallPolicy, setMarketInstallPolicy } from "@/controllers/API/dshMarket";
import type { MarketInstallPolicy } from "@/controllers/API/dshMarket";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

interface InstallPolicySettingsProps {
    tenant: number;
}

const fields = ["allow_third_party_plugins", "allow_third_party_workbenches"] as const;

export function InstallPolicySettings({ tenant }: InstallPolicySettingsProps) {
    const { t } = useTranslation("dshMarket");
    const [policy, setPolicy] = useState<MarketInstallPolicy | null>(null);
    const [pending, setPending] = useState(false);
    const [error, setError] = useState(false);
    const [revision, setRevision] = useState(0);

    useEffect(() => {
        const controller = new AbortController();
        setPolicy(null);
        setError(false);
        getMarketInstallPolicy(tenant, controller.signal)
            .then(value => { if (!controller.signal.aborted) setPolicy(value); })
            .catch(() => { if (!controller.signal.aborted) setError(true); });
        return () => controller.abort();
    }, [tenant, revision]);

    async function handleChange(field: typeof fields[number], allowed: boolean) {
        if (!policy || pending) return;
        setPending(true);
        try {
            const saved = await setMarketInstallPolicy(tenant, field, allowed);
            setPolicy(saved);
        } catch {
            toast({ title: t("policySaveFailed"), description: "", variant: "error" });
            setRevision(value => value + 1);
        } finally {
            setPending(false);
        }
    }

    return <section className="rounded-lg border p-4 space-y-3" aria-label={t("installPolicy")}>
        <h2 className="font-semibold">{t("installPolicy")}</h2>
        {error && <button type="button" className="text-sm text-destructive" onClick={() => setRevision(value => value + 1)}>{t("policyLoadFailed")}</button>}
        {fields.map(field => <div key={field} className="flex min-h-11 items-center justify-between gap-4">
            <label htmlFor={field} className="cursor-pointer text-sm">{t(field)}</label>
            <Switch id={field} checked={policy?.[field] ?? false} disabled={!policy || pending}
                onCheckedChange={allowed => void handleChange(field, allowed)} />
        </div>)}
    </section>;
}
