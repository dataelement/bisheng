import DefaultLoadingIcon from "@/components/bs-icons/loading/Loading.svg?react";
import type { BrandAsset, BrandConfig } from "@/controllers/API";
import { withBrandBaseUrl } from "@/utils/brand";
import { Monitor } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { BrandAssetKey, BrandPreviewTarget } from "./brandTypes";
import { DEFAULT_BRAND_CONFIG } from "./brandTypes";

interface BrandPreviewPanelProps {
    config: BrandConfig;
    target: BrandPreviewTarget | null;
    dark: boolean;
}

const PREVIEW_LABEL_KEYS: Record<BrandPreviewTarget, string> = {
    brandName: "theme.brandSystemName",
    favicon: "theme.brandFavicon",
    loginHeroLight: "theme.brandLoginHeroLight",
    loginHeroDark: "theme.brandLoginHeroDark",
    headerLogoLight: "theme.brandHeaderLogoLight",
    headerLogoDark: "theme.brandHeaderLogoDark",
    loadingIcon: "theme.brandLoadingIcon",
    loadingAnimation: "theme.brandLoadingAnimation",
};

const cx = (...classes: Array<string | false | null | undefined>) => (
    classes.filter(Boolean).join(" ")
);

const getImageUrl = (asset: BrandAsset | undefined, fallback: string) => (
    withBrandBaseUrl(asset?.url || fallback)
);

const getLocalizedText = (text?: { zh?: string; en?: string }) => (
    text?.zh || text?.en || ""
);

function Highlight({
    active,
    children,
    className = "",
}: {
    active: boolean;
    children: ReactNode;
    className?: string;
}) {
    return (
        <div
            className={cx(
                "relative rounded-md",
                active && "z-10 ring-[3px] ring-primary ring-offset-[3px] ring-offset-background shadow-[0_0_0_8px_rgba(0,89,255,0.18)]",
                className
            )}
        >
            {children}
        </div>
    );
}

function SkeletonLine({ className = "" }: { className?: string }) {
    return <div className={cx("h-3 rounded bg-muted", className)} />;
}

function MockBrowserFrame({
    title,
    faviconUrl,
    target,
    children,
}: {
    title: string;
    faviconUrl: string;
    target: BrandPreviewTarget;
    children: ReactNode;
}) {
    return (
        <div className="overflow-hidden rounded-md border bg-background shadow-sm">
            <div className="flex h-10 items-center gap-2 border-b bg-muted px-3">
                <Highlight active={target === "favicon"} className="shrink-0">
                    <img src={faviconUrl} alt="" className="size-5 rounded object-contain" />
                </Highlight>
                <Highlight active={target === "brandName"} className="min-w-0">
                    <div className="max-w-[180px] truncate rounded bg-background px-3 py-1 text-xs text-foreground">
                        {title}
                    </div>
                </Highlight>
                <div className="ml-auto flex gap-1">
                    <span className="size-2 rounded-full bg-border" />
                    <span className="size-2 rounded-full bg-border" />
                    <span className="size-2 rounded-full bg-border" />
                </div>
            </div>
            {children}
        </div>
    );
}

function LoginPreview({
    config,
    target,
}: {
    config: BrandConfig;
    target: BrandPreviewTarget;
}) {
    const isDarkHero = target === "loginHeroDark" || target === "headerLogoDark";
    const heroKey: BrandAssetKey = isDarkHero ? "loginHeroDark" : "loginHeroLight";
    const logoKey: BrandAssetKey = target === "headerLogoDark" ? "headerLogoDark" : "headerLogoLight";
    const faviconUrl = getImageUrl(config.assets.favicon, DEFAULT_BRAND_CONFIG.assets.favicon.url);
    const title = getLocalizedText(config.brandName) || "BISHENG";

    return (
        <MockBrowserFrame title={title} faviconUrl={faviconUrl} target={target}>
            <div className="grid h-[410px] grid-cols-[190px_minmax(0,1fr)] bg-background p-4">
                <Highlight active={target === "loginHeroLight" || target === "loginHeroDark"} className="h-full overflow-hidden">
                    <img
                        src={getImageUrl(config.assets[heroKey], DEFAULT_BRAND_CONFIG.assets[heroKey].url)}
                        alt=""
                        className="h-full w-full rounded-md object-cover"
                    />
                </Highlight>
                <div className="flex min-w-0 items-center justify-center px-7">
                    <div className="w-full max-w-[260px] space-y-5">
                        <Highlight active={target === "headerLogoLight" || target === "headerLogoDark"} className="mx-auto w-fit">
                            <img
                                src={getImageUrl(config.assets[logoKey], DEFAULT_BRAND_CONFIG.assets[logoKey].url)}
                                alt=""
                                className="h-10 max-w-[170px] object-contain"
                            />
                        </Highlight>
                        <div className="space-y-3">
                            <SkeletonLine className="h-9" />
                            <SkeletonLine className="h-9" />
                            <SkeletonLine className="h-9 w-2/3" />
                            <div className="h-10 rounded-md bg-primary/80" />
                        </div>
                    </div>
                </div>
            </div>
        </MockBrowserFrame>
    );
}

function AdminPreview({
    config,
    target,
}: {
    config: BrandConfig;
    target: BrandPreviewTarget;
}) {
    const logoKey: BrandAssetKey = target === "headerLogoDark" ? "headerLogoDark" : "headerLogoLight";
    const faviconUrl = getImageUrl(config.assets.favicon, DEFAULT_BRAND_CONFIG.assets.favicon.url);
    const title = getLocalizedText(config.brandName) || "BISHENG";

    return (
        <MockBrowserFrame title={title} faviconUrl={faviconUrl} target={target}>
            <div className="h-[410px] bg-accent p-4">
                <div className="flex h-full overflow-hidden rounded-md border bg-background">
                    <div className="w-[110px] border-r bg-muted/40 p-3">
                        <Highlight active={target === "headerLogoLight" || target === "headerLogoDark"}>
                            <img
                                src={getImageUrl(config.assets[logoKey], DEFAULT_BRAND_CONFIG.assets[logoKey].url)}
                                alt=""
                                className="h-8 max-w-[86px] object-contain"
                            />
                        </Highlight>
                        <div className="mt-7 space-y-4">
                            {Array.from({ length: 7 }).map((_, index) => (
                                <div key={index} className="flex items-center gap-2">
                                    <span className="size-4 rounded bg-slate-300" />
                                    <SkeletonLine className="w-12" />
                                </div>
                            ))}
                        </div>
                    </div>
                    <div className="min-w-0 flex-1 p-4">
                        <div className="mb-4 flex justify-end gap-2">
                            <SkeletonLine className="h-8 w-16" />
                            <SkeletonLine className="h-8 w-16" />
                        </div>
                        <div className="space-y-3">
                            <SkeletonLine className="h-9" />
                            <div className="grid grid-cols-2 gap-3">
                                <SkeletonLine className="h-24" />
                                <SkeletonLine className="h-24" />
                            </div>
                            <SkeletonLine className="h-28" />
                        </div>
                    </div>
                </div>
            </div>
        </MockBrowserFrame>
    );
}

function LoadingPreview({
    config,
    target,
}: {
    config: BrandConfig;
    target: BrandPreviewTarget;
}) {
    const faviconUrl = getImageUrl(config.assets.favicon, DEFAULT_BRAND_CONFIG.assets.favicon.url);
    const title = getLocalizedText(config.brandName) || "BISHENG";
    const loadingIconUrl = withBrandBaseUrl(config.URLLoadingIcon || config.loading?.icon?.url || "");

    return (
        <MockBrowserFrame title={title} faviconUrl={faviconUrl} target={target}>
            <div className="relative flex h-[410px] items-center justify-center bg-background">
                <div className="absolute inset-x-8 top-24 grid grid-cols-3 gap-3 opacity-40 blur-sm">
                    {Array.from({ length: 6 }).map((_, index) => (
                        <SkeletonLine key={index} className="h-16" />
                    ))}
                </div>
                <Highlight active={target === "loadingIcon" || target === "loadingAnimation"} className="bg-background p-5 shadow">
                    {loadingIconUrl ? (
                        <img
                            src={loadingIconUrl}
                            alt=""
                            className={cx("size-12 object-contain", config.loading.animation || "")}
                        />
                    ) : (
                        <DefaultLoadingIcon className={cx("size-12 text-primary", config.loading.animation || "")} />
                    )}
                </Highlight>
            </div>
        </MockBrowserFrame>
    );
}

function EmptyPreview() {
    const { t } = useTranslation();
    return (
        <div className="flex h-[464px] items-center justify-center rounded-md border border-dashed bg-muted/30 p-6">
            <div className="w-full max-w-[320px] space-y-4">
                <div className="flex justify-center">
                    <div className="flex size-12 items-center justify-center rounded-md bg-background text-muted-foreground shadow-sm">
                        <Monitor className="size-6" />
                    </div>
                </div>
                <p className="text-center text-sm text-muted-foreground">{t("theme.brandPreviewEmpty")}</p>
                <div className="rounded-md border bg-background p-4">
                    <SkeletonLine className="mb-3 h-8" />
                    <div className="grid grid-cols-[80px_minmax(0,1fr)] gap-3">
                        <SkeletonLine className="h-28" />
                        <div className="space-y-2">
                            <SkeletonLine />
                            <SkeletonLine className="w-5/6" />
                            <SkeletonLine className="h-16" />
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}

export default function BrandPreviewPanel({ config, target, dark }: BrandPreviewPanelProps) {
    const { t } = useTranslation();
    const resolvedTarget = target;

    const renderPreview = () => {
        if (!resolvedTarget) return <EmptyPreview />;
        if (resolvedTarget === "loadingIcon" || resolvedTarget === "loadingAnimation") {
            return <LoadingPreview config={config} target={resolvedTarget} />;
        }
        if (resolvedTarget === "headerLogoLight" || resolvedTarget === "headerLogoDark") {
            return <AdminPreview config={config} target={resolvedTarget} />;
        }
        const loginTargets: BrandPreviewTarget[] = ["brandName", "favicon", "loginHeroLight", "loginHeroDark"];
        if (loginTargets.includes(resolvedTarget)) {
            return <LoginPreview config={config} target={resolvedTarget} />;
        }
        return <AdminPreview config={config} target={dark ? "headerLogoDark" : "headerLogoLight"} />;
    };

    return (
        <aside className="h-fit space-y-4 rounded-md border border-border bg-background p-4 xl:sticky xl:top-5">
            <div className="flex min-h-6 items-center justify-between gap-3">
                <h3 className="text-base font-medium">{t("theme.brandPreview")}</h3>
                {resolvedTarget && (
                    <span className="truncate rounded bg-primary/10 px-2 py-1 text-xs text-primary">
                        {t(PREVIEW_LABEL_KEYS[resolvedTarget])}
                    </span>
                )}
            </div>
            {renderPreview()}
        </aside>
    );
}
