import { Outlined } from "bisheng-icons";
import { useState } from "react";
import { AccountSection } from "~/components/Settings/sections/AccountSection";
import { useAuthContext, useLocalize } from "~/hooks";

/**
 * 账号信息 section of the settings page: basic info + security (AccountSection)
 * plus the sign-out action, which moved here from the retired avatar pop menu.
 */
export function AccountPane() {
  const localize = useLocalize();
  const { user, logout } = useAuthContext();
  const displayName = user?.username || "admin";
  const [avatarUrl, setAvatarUrl] = useState<string>(user?.avatar || "");

  return (
    <div className="flex flex-col gap-6">
      <AccountSection
        username={displayName}
        avatarUrl={avatarUrl || user?.avatar || ""}
        onAvatarUpdated={setAvatarUrl}
      />

      <section className="flex flex-col gap-4 border-t border-fill-2 pt-5">
        <button
          type="button"
          onClick={() => logout()}
          className="flex h-9 w-fit items-center gap-2 rounded-lg border border-[#f53f3f]/30 px-4 text-[14px] font-medium text-[#f53f3f] transition-colors hover:bg-red-50"
        >
          <Outlined.LogOut className="size-4" />
          {localize("com_nav_log_out")}
        </button>
      </section>
    </div>
  );
}
