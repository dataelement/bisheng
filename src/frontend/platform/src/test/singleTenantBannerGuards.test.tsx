// Tenant-flavoured banners must disappear on a single-tenant deployment.
//
// `multi_tenant.enabled` defaults to false on a standard docker install, where
// there is exactly one (Root) tenant, no scope switcher and nothing to inherit
// from. Both banners below explain Root↔child mechanics, so they are guarded on
// `appConfig.multiTenantEnabled` rather than reworded.

import { ReactElement, ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { locationContext } from "@/contexts/locationContext";
import ConfigInheritanceBanner from "@/pages/BuildPage/bench/ConfigInheritanceBanner";
import { ScopeBanner } from "@/pages/ModelPage/manage/SystemConfigBanners";
import { render } from "@/test/test-utils";
import { Tenant } from "@/types/api/tenant";

// The shared setup mock returns the bare key, which would hide the interpolated
// tenant name. Append the interpolation values so the display-name fix is
// observable in the DOM.
vi.mock("react-i18next", () => ({
    useTranslation: () => ({
        t: (key: string, options?: Record<string, unknown>) =>
            options ? `${key}|${Object.values(options).join("|")}` : key,
        i18n: { changeLanguage: vi.fn(), language: "en" },
    }),
    Trans: ({ children }: { children: ReactNode }) => children,
    initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

// Stand-in for whatever `tenant.defaultName` resolves to in a real locale
// bundle; only the fact that the seed name was translated matters here.
const LOCALIZED_DEFAULT_TENANT = "TenantNameLocalized";

// `displayTenantName` localizes through the i18next singleton, which is never
// initialized in tests.
vi.mock("i18next", () => ({
    default: {
        t: (key: string, options?: { defaultValue?: string }) =>
            key === "tenant.defaultName" ? LOCALIZED_DEFAULT_TENANT : (options?.defaultValue ?? key),
    },
}));

const contextValue = (multiTenantEnabled: boolean) => ({
    current: [],
    setCurrent: () => { },
    isStackedOpen: false,
    setIsStackedOpen: () => { },
    showSideBar: false,
    setShowSideBar: () => { },
    extraNavigation: { title: "" },
    setExtraNavigation: () => { },
    extraComponent: null,
    setExtraComponent: () => { },
    appConfig: { multiTenantEnabled },
    reloadConfig: () => { },
});

const renderWithTenancy = (ui: ReactElement, multiTenantEnabled: boolean) =>
    render(
        <locationContext.Provider value={contextValue(multiTenantEnabled)}>
            {ui}
        </locationContext.Provider>,
    );

const rootTenant = { tenant_name: "Default Tenant" } as Tenant;

describe("ConfigInheritanceBanner", () => {
    // The backend short-circuits single-tenant reads to
    // `(value, inherited=False, DEFAULT_TENANT_ID, has_override=True)`, so this
    // meta is exactly what a single-tenant workbench config request returns.
    const singleTenantMeta = { inherited_from_root: false, has_override: true };

    it("renders nothing on a single-tenant deployment", () => {
        const { container } = renderWithTenancy(
            <ConfigInheritanceBanner meta={singleTenantMeta} />,
            false,
        );
        expect(container).toBeEmptyDOMElement();
    });

    it("still renders the override banner on a multi-tenant deployment", () => {
        const { container } = renderWithTenancy(
            <ConfigInheritanceBanner meta={singleTenantMeta} />,
            true,
        );
        expect(container.textContent).toContain("tenant.currentOverride");
    });

    it("still renders the inherited banner on a multi-tenant deployment", () => {
        const { container } = renderWithTenancy(
            <ConfigInheritanceBanner meta={{ inherited_from_root: true }} />,
            true,
        );
        expect(container.textContent).toContain("tenant.inheritedFromRoot");
    });
});

describe("ScopeBanner", () => {
    it("renders nothing on a single-tenant deployment", () => {
        const { container } = renderWithTenancy(
            <ScopeBanner isGlobalSuper scopeTenantId={null} rootTenant={rootTenant} />,
            false,
        );
        expect(container).toBeEmptyDOMElement();
    });

    it("hides the child-admin variant too, which is equally tenant-flavoured", () => {
        const { container } = renderWithTenancy(
            <ScopeBanner isGlobalSuper={false} scopeTenantId={1} rootTenant={rootTenant} />,
            false,
        );
        expect(container).toBeEmptyDOMElement();
    });

    it("localizes the seeded Default Tenant name instead of leaking the English seed", () => {
        const { container } = renderWithTenancy(
            <ScopeBanner isGlobalSuper scopeTenantId={null} rootTenant={rootTenant} />,
            true,
        );
        expect(container.textContent).toContain("model.systemConfigRootBanner");
        expect(container.textContent).toContain(LOCALIZED_DEFAULT_TENANT);
        expect(container.textContent).not.toContain("Default Tenant");
    });
});
