import { X } from "lucide-react";
import { Dialog, DialogContent } from "~/components/ui/Dialog";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import { AccountSection } from "./sections/AccountSection";
import { GeneralSection } from "./sections/GeneralSection";
import type { SettingsSection } from "./useSettingsDialog";

const NAV_ITEMS: { key: SettingsSection; labelKey: string }[] = [
    { key: "account", labelKey: "com_account_info_title" },
    { key: "general", labelKey: "com_settings_general" },
];

export interface SettingsDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    section: SettingsSection;
    onSectionChange: (section: SettingsSection) => void;
    username?: string;
    avatarUrl?: string;
    onAvatarUpdated?: (url: string) => void;
}

/**
 * Unified personal settings dialog: left nav (account / storage / general) +
 * content pane. Replaces the standalone AccountInfoDialog and absorbs the
 * storage card, language switch and font size from the profile menu.
 */
export function SettingsDialog({
    open,
    onOpenChange,
    section,
    onSectionChange,
    username = "admin",
    avatarUrl = "",
    onAvatarUpdated,
}: SettingsDialogProps) {
    const localize = useLocalize();

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent
                close={false}
                className={cn(
                    "flex h-[600px] max-h-[calc(100vh-32px)] w-[760px] max-w-[calc(100vw-32px)] flex-col gap-0 overflow-hidden rounded-xl sm:rounded-xl border border-[#ECECEC] bg-white p-0 shadow-[0_8px_24px_rgba(15,23,42,0.12)]",
                    // H5: full-screen page (tailwind touch-mobile = max-width 1023px)
                    "touch-mobile:inset-x-0 touch-mobile:bottom-0 touch-mobile:left-0 touch-mobile:right-0 touch-mobile:top-0 touch-mobile:h-[100dvh] touch-mobile:max-h-[100dvh] touch-mobile:w-full touch-mobile:max-w-none touch-mobile:translate-x-0 touch-mobile:translate-y-0 touch-mobile:rounded-none touch-mobile:border-0 touch-mobile:shadow-none",
                )}
            >
                {/* Title bar */}
                <div className="flex h-12 w-full shrink-0 items-center justify-between border-b border-[#f2f3f5] px-5 touch-mobile:px-4">
                    <h2 className="text-[16px] font-semibold leading-6 text-[#1d2129]">
                        {localize("com_nav_settings")}
                    </h2>
                    <button
                        type="button"
                        onClick={() => onOpenChange(false)}
                        className="rounded-lg text-[#86909c] opacity-70 transition-opacity hover:opacity-100 focus:outline-none"
                        aria-label={localize("com_ui_close")}
                    >
                        <X className="h-4 w-4" />
                    </button>
                </div>

                <div className="flex min-h-0 flex-1 touch-mobile:flex-col">
                    {/* Desktop: vertical nav on the left */}
                    <nav className="hidden w-[168px] shrink-0 flex-col gap-1 border-r border-[#f2f3f5] p-2 touch-desktop:flex">
                        {NAV_ITEMS.map((item) => (
                            <button
                                key={item.key}
                                type="button"
                                className={cn(
                                    "flex h-8 items-center rounded-lg px-3 text-left text-[14px] transition-colors",
                                    section === item.key
                                        ? "bg-[#f2f3f5] font-medium text-[#1d2129]"
                                        : "text-[#4e5969] hover:bg-[#f7f8fa]",
                                )}
                                onClick={() => onSectionChange(item.key)}
                            >
                                {localize(item.labelKey)}
                            </button>
                        ))}
                    </nav>

                    {/* Mobile: horizontal tabs under the title bar */}
                    <nav className="flex shrink-0 gap-1 overflow-x-auto border-b border-[#f2f3f5] px-4 pb-2 pt-1 touch-desktop:hidden">
                        {NAV_ITEMS.map((item) => (
                            <button
                                key={item.key}
                                type="button"
                                className={cn(
                                    "whitespace-nowrap rounded-full px-3 py-1.5 text-[13px] transition-colors",
                                    section === item.key
                                        ? "bg-[#f2f3f5] font-medium text-[#1d2129]"
                                        : "text-[#86909c]",
                                )}
                                onClick={() => onSectionChange(item.key)}
                            >
                                {localize(item.labelKey)}
                            </button>
                        ))}
                    </nav>

                    <div className="min-h-0 flex-1 overflow-y-auto p-4">
                        {section === "account" && (
                            <AccountSection
                                username={username}
                                avatarUrl={avatarUrl}
                                onAvatarUpdated={onAvatarUpdated}
                            />
                        )}
                        {section === "general" && <GeneralSection />}
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
}
