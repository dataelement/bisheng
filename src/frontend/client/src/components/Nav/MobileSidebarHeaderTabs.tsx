import { X } from "lucide-react";
import { useLocalize } from "~/hooks";
import { HubModuleNavTabs, type HubModuleLink } from "./HubModuleNavTabs";

interface MobileSidebarHeaderProps {
  logoSrc?: string;
  onClose?: () => void;
}

interface MobileSidebarHeaderTabsProps extends MobileSidebarHeaderProps {
  onLinkClick?: (link: HubModuleLink) => void;
}

/** Shared logo and close action for mobile sidebar headers. */
export function MobileSidebarHeader({ logoSrc, onClose }: MobileSidebarHeaderProps) {
  const localize = useLocalize();

  return (
    <div className="shrink-0 px-2 py-2.5">
      <div className="flex items-center justify-between">
        {logoSrc ? (
          <img
            className="h-8 w-8 rounded-md object-contain"
            src={logoSrc}
            alt={localize("com_nav_home")}
          />
        ) : (
          <div className="h-8 w-8 rounded-md bg-fill-2" />
        )}
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            aria-label={localize("com_nav_close_sidebar")}
            className="inline-flex size-8 items-center justify-center rounded-md text-text-2 hover:bg-fill-1"
          >
            <X className="size-4" />
          </button>
        ) : null}
      </div>
    </div>
  );
}

/** Channel and knowledge drawers retain their module navigation. */
export function MobileSidebarHeaderTabs({ logoSrc, onClose, onLinkClick }: MobileSidebarHeaderTabsProps) {
  return (
    <>
      <MobileSidebarHeader logoSrc={logoSrc} onClose={onClose} />
      <div className="shrink-0 pt-1">
        <HubModuleNavTabs equalWidth squareItems onLinkClick={onLinkClick} />
      </div>
    </>
  );
}
