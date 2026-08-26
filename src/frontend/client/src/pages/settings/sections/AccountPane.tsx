import { Outlined } from "bisheng-icons";
import { useState } from "react";
import { AccountSection } from "~/components/Settings/sections/AccountSection";
import { Button } from "~/components/ui/Button";
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
        <Button color="danger" variant="filled" className="w-fit" onClick={() => logout()}>
          <Outlined.LogOut />
          {localize("com_nav_log_out")}
        </Button>
      </section>
    </div>
  );
}
