import { Outlined } from "bisheng-icons";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AccountSection } from "~/components/Settings/sections/AccountSection";
import { Button } from "~/components/ui/Button";
import { useAuthContext, useLocalize } from "~/hooks";

/**
 * Account section of the settings page: basic information and security
 * plus the sign-out action, which moved here from the retired avatar pop menu.
 * The personal key moved to its own "AI assistant access" section (F066).
 */
export function AccountPane() {
  const localize = useLocalize();
  const { user, logout } = useAuthContext();
  const displayName = user?.username || "admin";
  const [avatarUrl, setAvatarUrl] = useState<string>(user?.avatar || "");
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  // Legacy deep link: install prompts distributed before F066 point here with
  // ?api-token=1. Keep them landing on the new section's connect flow.
  useEffect(() => {
    if (searchParams.get("api-token") === "1") {
      navigate("/settings/ai-access?connect=1", { replace: true });
    }
  }, [searchParams, navigate]);

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
