import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getPersonalTokenStatusApi } from "~/api/personalToken";
import { PersonalTokenDialog } from "~/components/PersonalTokenDialog";
import { Button } from "~/components/ui/Button";
import { useAuthContext, useLocalize } from "~/hooks";
import { useAiAccessUiEnabled, usePersonalTokenEnabled } from "~/hooks/useVersionManagementEnabled";
import { shouldShowAiAccessSection } from "./personalTokenEntry";

/**
 * "AI assistant access" settings section — the stable home for the personal
 * key lifecycle. Unlike the knowledge-page entry it stays visible while the
 * tenant switch is off, so a user whose assistant suddenly fails finds the
 * explanation here instead of a vanished entry.
 */
export function AiAccessPane() {
  const localize = useLocalize();
  const { user } = useAuthContext();
  const deploymentEnabled = usePersonalTokenEnabled();
  const uiEnabled = useAiAccessUiEnabled();
  const entryVisible = shouldShowAiAccessSection(deploymentEnabled, uiEnabled);
  const [searchParams, setSearchParams] = useSearchParams();
  const [dialogOpen, setDialogOpen] = useState(false);
  const { data: status } = useQuery({
    queryKey: ["personal-token-status", user?.id],
    queryFn: getPersonalTokenStatusApi,
    enabled: entryVisible && !!user?.id,
    retry: false,
  });
  const tenantEnabled = status?.enabled === true;
  const connectRequested = searchParams.get("connect") === "1";

  useEffect(() => {
    if (entryVisible && connectRequested && tenantEnabled) {
      setDialogOpen(true);
      setSearchParams((previous) => {
        const next = new URLSearchParams(previous);
        next.delete("connect");
        return next;
      }, { replace: true });
    }
  }, [entryVisible, connectRequested, tenantEnabled, setSearchParams]);

  if (!entryVisible) return null;

  const token = status?.token ?? null;
  const statusText = !token
    ? localize("com_ai_access.status_none")
    : token.revoked_at
      ? localize("com_ai_access.status_revoked")
      : token.is_valid
        ? localize("com_ai_access.status_active")
        : localize("com_ai_access.status_expired");

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-text-3">{localize("com_ai_access.section_desc")}</p>
      {tenantEnabled ? (
        <section className="flex items-center justify-between gap-4 rounded-xl border border-border-base p-4">
          <div className="text-sm">
            <span className="text-text-3">{localize("com_ai_access.status_label")}: </span>
            <span className="text-text-1">{statusText}</span>
          </div>
          <Button variant={token ? "outline" : undefined} onClick={() => setDialogOpen(true)}>
            {localize(token ? "com_ai_access.manage" : "com_ai_access.guide_title")}
          </Button>
        </section>
      ) : (
        <section className="rounded-xl border border-dashed border-border-base bg-fill-1 p-4 text-sm text-text-2">
          {localize("com_ai_access.disabled_notice")}
        </section>
      )}
      <PersonalTokenDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </div>
  );
}
