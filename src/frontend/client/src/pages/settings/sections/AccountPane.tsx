import { Outlined } from "bisheng-icons";
import { useState } from "react";
import { PersonalTokenDialog } from "~/components/PersonalTokenDialog";
import { AccountSection } from "~/components/Settings/sections/AccountSection";
import { Button } from "~/components/ui/Button";
import { useAuthContext, useLocalize } from "~/hooks";
import { usePersonalTokenEnabled } from "~/hooks/useVersionManagementEnabled";

/**
 * Account section of the settings page: basic information and security
 * plus the sign-out action, which moved here from the retired avatar pop menu.
 */
export function AccountPane() {
  const localize = useLocalize();
  const { user, logout } = useAuthContext();
  const displayName = user?.username || "admin";
  const [avatarUrl, setAvatarUrl] = useState<string>(user?.avatar || "");
  const [tokenDialogOpen, setTokenDialogOpen] = useState(false);
  const personalTokenEnabled = usePersonalTokenEnabled();

  return (
    <div className="flex flex-col gap-6">
      <AccountSection
        username={displayName}
        avatarUrl={avatarUrl || user?.avatar || ""}
        onAvatarUpdated={setAvatarUrl}
      />

      {personalTokenEnabled ? (
        <section className="flex items-center justify-between gap-4 border-t border-fill-2 pt-5">
          <div>
            <h3 className="text-sm font-medium text-text-1">{localize("com_personal_token_title")}</h3>
            <p className="mt-1 text-sm text-text-3">{localize("com_personal_token_account_hint")}</p>
          </div>
          <Button variant="outline" onClick={() => setTokenDialogOpen(true)}>
            {localize("com_personal_token_manage")}
          </Button>
        </section>
      ) : null}

      <section className="flex flex-col gap-4 border-t border-fill-2 pt-5">
        <Button color="danger" variant="filled" className="w-fit" onClick={() => logout()}>
          <Outlined.LogOut />
          {localize("com_nav_log_out")}
        </Button>
      </section>
      <PersonalTokenDialog open={tokenDialogOpen} onOpenChange={setTokenDialogOpen} />
    </div>
  );
}
