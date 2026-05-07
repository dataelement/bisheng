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
 * Renders one of three messages and never two — the conditions are exclusive.
 */
export function ScopeBanner({
    isGlobalSuper,
    scopeTenantId,
    rootTenant,
    childTenant,
}: ScopeBannerProps): JSX.Element | null {
    const { t } = useTranslation('model');
    const isRootScope = scopeTenantId === null || scopeTenantId === ROOT_TENANT_ID;

    if (isGlobalSuper && isRootScope) {
        return (
            <div className="mb-4 p-3 rounded-md bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 text-sm text-blue-900 dark:text-blue-100">
                {t('model.systemConfigRootBanner')}
            </div>
        );
    }
    if (!isRootScope) {
        const tenantName = childTenant?.tenant_name || childTenant?.tenant_code || '';
        return (
            <div className="mb-4 p-3 rounded-md bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 text-sm text-amber-900 dark:text-amber-100">
                {t('model.systemConfigTenantBanner', { tenantName })}
            </div>
        );
    }
    // !isGlobalSuper && isRootScope: Child user viewing Root — read-only.
    return (
        <div className="mb-4 p-3 rounded-md bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-sm text-gray-700 dark:text-gray-300">
            {t('model.systemConfigRootReadOnlyBanner')}
        </div>
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
        <div className="mb-3 p-3 rounded-md bg-yellow-50 dark:bg-yellow-950 border border-yellow-200 dark:border-yellow-800 text-sm text-yellow-900 dark:text-yellow-100">
            {t('model.systemConfigFallbackBlockedBanner')}
        </div>
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
        <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200">
            {t('model.systemConfigInheritedBadge')}
        </span>
    );
}
