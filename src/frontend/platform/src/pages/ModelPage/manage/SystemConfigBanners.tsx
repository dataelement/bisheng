// F022 system-config envelope banners + badge.
//
// Three concerns, kept tight:
//   * <ScopeBanner>           — top-of-dialog banner driven by useAdminScope
//                                + isGlobalSuper. 3 mutually exclusive states.
//   * <FallbackBlockedBanner> — per-tab Banner shown when the GET envelope
//                                returns fallback_blocked=true (Root has a row
//                                but disabled share).
//   * <InheritedBadge>        — small inline Badge shown next to a tab title
//                                when the GET envelope returns
//                                inherited_from_root=true.

import { Alert, Tag } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import { Tenant } from "@/types/api/tenant";
import { User } from "@/types/api/user";

const ROOT_TENANT_ID = 1;

export interface ScopeBannerProps {
    isGlobalSuper: boolean;
    scopeTenantId: number | null; // null = no scope (Root super view)
    rootTenant?: Tenant | null;
    childTenant?: Tenant | null; // resolved from current scope
}

/**
 * Top-of-dialog banner explaining who the configuration is being applied to.
 * Renders one of three messages, all parameterized on the tenant's display
 * name (so deployments where Root is named e.g. "默认租户" don't show a
 * hard-coded "Root").
 */
export function ScopeBanner({
    isGlobalSuper,
    scopeTenantId,
    rootTenant,
    childTenant,
}: ScopeBannerProps): JSX.Element | null {
    const { t } = useTranslation('model');
    const isRootScope = scopeTenantId === null || scopeTenantId === ROOT_TENANT_ID;
    // Resolve the display name for whichever tenant the banner is about.
    // The fallback chain (name → code → "Root") avoids a blank substitution
    // on the rare deployments where the Root tenant has no display name set.
    const rootName = rootTenant?.tenant_name || rootTenant?.tenant_code || 'Root';

    if (isGlobalSuper && isRootScope) {
        return (
            <Alert
                className="mb-4"
                description={t('model.systemConfigRootBanner', { tenantName: rootName })}
            />
        );
    }
    if (!isRootScope) {
        const tenantName = childTenant?.tenant_name || childTenant?.tenant_code || '';
        return (
            <Alert
                type="warning"
                className="mb-4"
                description={t('model.systemConfigTenantBanner', { tenantName, rootName })}
            />
        );
    }
    // !isGlobalSuper: Child Admin (or dept admin) on their own tenant. They
    // do not see a scope switcher (super-only), but write target resolves
    // to their leaf tenant via `_resolve_write_target` + JWT, and
    // `_assert_can_write_system_config` admits them via tenant#admin —
    // i.e. they CAN edit. Mirror the amber "editing my tenant" framing
    // that super sees in the !isRootScope branch above; do not tell them
    // to "switch view" since that UI does not exist for them.
    return (
        <Alert
            type="warning"
            className="mb-4"
            description={t('model.systemConfigChildOwnBanner', { rootName })}
        />
    );
}

/**
 * Per-tab banner shown when Root holds a value but has fallback sharing
 * disabled — the current Child has nothing to inherit and must configure
 * its own row or get the operator to flip Root's share toggle.
 */
export function FallbackBlockedBanner({ visible }: { visible: boolean }): JSX.Element | null {
    const { t } = useTranslation('model');
    if (!visible) return null;
    return (
        <Alert
            type="warning"
            className="mb-3"
            description={t('model.systemConfigFallbackBlockedBanner')}
        />
    );
}

/**
 * Inline Badge shown near the tab title when the current value came from
 * Root via share-default-to-children fallback. Disappears the moment the
 * user edits any field (the parent clears the inherited flag locally).
 */
export function InheritedBadge({ visible }: { visible: boolean }): JSX.Element | null {
    const { t } = useTranslation('model');
    if (!visible) return null;
    return (
        <Tag size="small" color="brand" className="ml-2">
            {t('model.systemConfigInheritedBadge')}
        </Tag>
    );
}
