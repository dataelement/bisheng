import { useContext } from "react";
import { Alert } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import { locationContext } from "@/contexts/locationContext";

export interface ConfigEnvelopeMeta {
    inherited_from_root?: boolean;
    source_tenant_id?: number;
    has_override?: boolean;
    /**
     * Nothing was stored for this scope, so `data` is the backend's built-in
     * default rather than anything an admin saved. The config forms round-trip
     * whatever they are given, so saving a fallback would persist defaults over
     * a real config — see the save guard in `bench/index.tsx`.
     */
    is_fallback?: boolean;
}

export function resolveConfigEnvelope<T>(value: any): { data: T | null; meta: ConfigEnvelopeMeta } {
    if (
        value &&
        typeof value === "object" &&
        "data" in value &&
        ("inherited_from_root" in value || "has_override" in value || "source_tenant_id" in value)
    ) {
        const envelope = value as {
            data?: T;
            inherited_from_root?: unknown;
            source_tenant_id?: unknown;
            has_override?: unknown;
            is_fallback?: unknown;
        };
        return {
            data: envelope.data ?? null,
            meta: {
                inherited_from_root: !!envelope.inherited_from_root,
                source_tenant_id: typeof envelope.source_tenant_id === "number" ? envelope.source_tenant_id : undefined,
                has_override: !!envelope.has_override,
                is_fallback: !!envelope.is_fallback,
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
    const { appConfig } = useContext(locationContext);
    // Single-tenant deployments (`multi_tenant.enabled=false`, the default of a
    // standard docker install) always land in the `hasOverride` branch: the
    // backend short-circuits to `(value, inherited=False, DEFAULT_TENANT_ID,
    // has_override=True)` and `endpoints/config.py` ships those fields
    // unconditionally. The banner would then permanently claim "this tenant has
    // its own configuration" on a platform that has no tenants to compare
    // against. Every branch here is about Root↔child inheritance, so drop the
    // whole block rather than reword it.
    if (!appConfig.multiTenantEnabled) return null;
    if (!meta) return null;
    const inherited = !!meta.inherited_from_root;
    const hasOverride = meta.has_override === true;
    const unresolved = meta.has_override === false && !inherited;
    if (!inherited && !hasOverride && !unresolved) return null;
    // The three states keep the semantics their old hand-rolled tints carried:
    // inheriting is neutral information, an override is a settled state, and an
    // unresolved scope is the one the admin still has to act on.
    const type = inherited ? "info" : hasOverride ? "success" : "warning";
    const description = inherited
        ? t("tenant.inheritedFromRoot")
        : hasOverride
          ? t("tenant.currentOverride")
          : t("tenant.noOverrideYet");
    return <Alert type={type} description={description} />;
}
