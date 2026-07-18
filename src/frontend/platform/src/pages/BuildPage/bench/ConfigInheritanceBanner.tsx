import { useTranslation } from "react-i18next";

export interface ConfigEnvelopeMeta {
    inherited_from_root?: boolean;
    source_tenant_id?: number;
    has_override?: boolean;
}

export function resolveConfigEnvelope<T>(value: any): { data: T | null; meta: ConfigEnvelopeMeta } {
    if (
        value &&
        typeof value === "object" &&
        "data" in value &&
        ("inherited_from_root" in value || "has_override" in value || "source_tenant_id" in value)
    ) {
        return {
            data: (value as any).data ?? null,
            meta: {
                inherited_from_root: !!(value as any).inherited_from_root,
                source_tenant_id: typeof (value as any).source_tenant_id === "number" ? (value as any).source_tenant_id : undefined,
                has_override: !!(value as any).has_override,
            },
        };
    }
    return {
        data: value ?? null,
        meta: {},
    };
}

export default function ConfigInheritanceBanner({ meta }: { meta?: ConfigEnvelopeMeta | null }) {
    const { t } = useTranslation();
    if (!meta) return null;
    const inherited = !!meta.inherited_from_root;
    const hasOverride = meta.has_override === true;
    const unresolved = meta.has_override === false && !inherited;
    if (!inherited && !hasOverride && !unresolved) return null;
    return (
        <div
            className={
                inherited
                    ? "mb-4 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700"
                    : hasOverride
                        ? "mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700"
                        : "mb-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700"
            }
        >
            {inherited
                ? t("tenant.inheritedFromRoot", { defaultValue: "当前使用根租户配置" })
                : hasOverride
                    ? t("tenant.currentOverride", { defaultValue: "当前租户已独立配置" })
                    : t("tenant.noOverrideYet", { defaultValue: "当前尚未保存独立配置" })}
        </div>
    );
}
