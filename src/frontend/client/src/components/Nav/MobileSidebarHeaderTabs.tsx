import { X } from "lucide-react";
import { useLocalize } from "~/hooks";
import { HubModuleNavTabs, type HubModuleLink } from "./HubModuleNavTabs";

interface MobileSidebarHeaderTabsProps {
  logoSrc?: string;
  onClose?: () => void;
  onLinkClick?: (link: HubModuleLink) => void;
}

/** Unified mobile drawer chrome used by app/channel/knowledge sidebars. */
export function MobileSidebarHeaderTabs({
  logoSrc,
  onClose,
  onLinkClick,
}: MobileSidebarHeaderTabsProps) {
  const localize = useLocalize();

  return (
    <>
      <div className="shrink-0 px-3 py-2.5">
        <div className="flex items-center justify-between">
          {logoSrc ? (
            <img
              className="h-8 w-8 rounded-md object-contain"
              src={logoSrc}
              alt={localize("com_nav_home")}
            />
          ) : (
            <div className="h-8 w-8 rounded-md bg-[#F2F3F5]" />
          )}
          {onClose ? (
            <button
              type="button"
              onClick={onClose}
              aria-label={localize("com_nav_close_sidebar")}
              className="inline-flex size-8 items-center justify-center rounded-md text-[#4E5969] hover:bg-[#F7F8FA]"
            >
              <X className="size-4" />
            </button>
          ) : null}
        </div>
      </div>
      <div className="shrink-0 pt-1">
        <HubModuleNavTabs
          equalWidth
          squareItems
          onLinkClick={onLinkClick}
        />
      </div>
    </>
  );
}

