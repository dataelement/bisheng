import { Outlined } from "bisheng-icons";
import { useEffect, useRef, useState } from "react";
import {
  deletePersonalTokenApi,
  getPersonalTokenGuideUrls,
  getPersonalTokenInstallPromptApi,
  getPersonalTokenStatusApi,
  issuePersonalTokenApi,
  type PersonalTokenIssued,
  type PersonalTokenItem,
  type PersonalTokenStatus,
} from "~/api/personalToken";
import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  TooltipAnchor,
} from "~/components/ui";
import { useConfirm } from "~/Providers/ConfirmContext";
import { useToastContext } from "~/Providers/ToastContext";
import { useLocalize } from "~/hooks";
import { copyText } from "~/utils";

export interface PersonalTokenDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function formatDate(value: string | null): string {
  return value ? value.slice(0, 10) : "—";
}

interface TokenRevealDialogProps {
  issued: PersonalTokenIssued | null;
  /** Browser origin: the address the user's machine can reach, baked into the setup command. */
  baseUrl: string;
  onClose: () => void;
  onCopy: (value: string, doneMessage?: string) => void;
}

/** One-time key reveal stacked above the main dialog, on the same z-tier as
 * the confirm layer. Dismissing it (×/Esc/overlay) is always allowed: the key
 * is already stored, closing only hides the plaintext for good. */
function TokenRevealDialog({ issued, baseUrl, onClose, onCopy }: TokenRevealDialogProps) {
  const localize = useLocalize();
  const copyAllRef = useRef<HTMLButtonElement>(null);
  return (
    <Dialog open={issued !== null} onOpenChange={(nextOpen) => { if (!nextOpen) onClose(); }}>
      <DialogContent
        overlayClassName="z-[110]"
        className="z-[110] w-[calc(100vw-32px)] max-w-[480px] gap-0 rounded-2xl p-6 shadow-modal"
        onOpenAutoFocus={(event) => { event.preventDefault(); copyAllRef.current?.focus(); }}
      >
        <DialogHeader className="space-y-0 pb-3 pr-8 text-left">
          <DialogTitle className="text-h4 font-medium text-text-1">
            {localize("com_ai_access.reveal_title")}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {localize("com_ai_access.once_banner")}
          </DialogDescription>
        </DialogHeader>
        {issued ? (
          <div className="space-y-3 text-body text-text-3">
            <p className="rounded-lg bg-danger-tint px-3 py-2 text-body-sm text-danger">
              {localize("com_ai_access.once_banner")}
            </p>
            <div className="flex items-start gap-2">
              <p className="min-w-0 flex-1 break-all">
                <span>{localize("com_ai_access.key_label")}: </span>
                <code>{issued.plaintext}</code>
              </p>
              <TooltipAnchor description={localize("com_ai_access.copy_key")}>
                <Button color="default" variant="text" iconOnly aria-label={localize("com_ai_access.copy_key")} onClick={() => onCopy(issued.plaintext)}>
                  <Outlined.Copy />
                </Button>
              </TooltipAnchor>
            </div>
            <Button
              ref={copyAllRef}
              color="default" variant="solid" size="large" className="w-full"
              onClick={() => onCopy(localize("com_ai_access.copy_send_all_body", { key: issued.plaintext, baseUrl }), localize("com_ai_access.copy_send_all_done"))}
            >
              {localize("com_ai_access.copy_send_all")}
            </Button>
            <p className="rounded-lg bg-danger-tint px-3 py-2 text-body-sm text-danger">
              {localize("com_ai_access.risk_banner")}
            </p>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

/** "AI assistant access" dialog: install-instruction step + personal key step. */
export function PersonalTokenDialog({ open, onOpenChange }: PersonalTokenDialogProps) {
  const localize = useLocalize();
  const confirm = useConfirm();
  const { showToast } = useToastContext();
  const [status, setStatus] = useState<PersonalTokenStatus | null>(null);
  const [issued, setIssued] = useState<PersonalTokenIssued | null>(null);
  const [loading, setLoading] = useState(false);
  const [action, setAction] = useState<"issue" | "delete" | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [reload, setReload] = useState(0);
  const [actionFailed, setActionFailed] = useState(false);
  // Inline pre-issue confirmation for administrator holders (AC-P17): the
  // acknowledge checkbox gates the actual issuance.
  const [adminConfirm, setAdminConfirm] = useState(false);
  const [adminAcknowledged, setAdminAcknowledged] = useState(false);
  // Origin the backend bakes into skill packs, kept only when it differs from
  // the browser's (admin-only diagnostic of a proxy chain hiding the address).
  const [packOrigin, setPackOrigin] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setStatus(null);
    setIssued(null);
    setLoadFailed(false);
    setActionFailed(false);
    setAdminConfirm(false);
    setAdminAcknowledged(false);
    setPackOrigin(null);
    setLoading(true);
    getPersonalTokenStatusApi()
      .then((next) => { if (!cancelled) setStatus(next); })
      .catch(() => { if (!cancelled) setLoadFailed(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [open, reload]);

  const holderIsAdmin = Boolean(status?.holder_is_admin);
  useEffect(() => {
    if (!open || !holderIsAdmin) return;
    let cancelled = false;
    getPersonalTokenInstallPromptApi()
      .then((result) => {
        if (cancelled) return;
        const origin = new URL(result.skill_pack_url).origin;
        setPackOrigin(origin === window.location.origin ? null : origin);
      })
      // Diagnostics only: a failure must never disturb the dialog.
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [open, holderIsAdmin]);

  const token = status?.token;
  const unavailable = !status?.enabled;
  const busy = loading || action !== null;
  const urls = getPersonalTokenGuideUrls(window.location.origin);
  const installPrompt = localize("com_ai_access.install_prompt", urls);
  // The narrowed tenant policy wins over administrator facts, so the heavier
  // admin ceremony only applies while the scope is still the wide default.
  const adminWideScope = Boolean(status?.holder_is_admin) && status?.data_scope !== "personal_only";
  const scopeText = status?.data_scope === "personal_only"
    ? localize("com_ai_access.scope_own_only")
    : status?.holder_is_admin
      ? localize("com_ai_access.scope_admin_all")
      : localize("com_ai_access.scope_all");

  const doIssue = async () => {
    setAction("issue");
    setActionFailed(false);
    setAdminConfirm(false);
    setAdminAcknowledged(false);
    try {
      const next = await issuePersonalTokenApi();
      setIssued(next);
      // Keep only the masked item in status so the plaintext never lingers
      // outside the reveal dialog.
      const item = { ...next } as PersonalTokenItem & { plaintext?: string };
      delete item.plaintext;
      setStatus((previous) => previous ? { ...previous, token: item } : previous);
    } catch {
      setActionFailed(true);
    } finally {
      setAction(null);
    }
  };

  const handleIssue = async () => {
    if (busy || unavailable) return;
    if (token && !await confirm({
      title: localize("com_ai_access.regenerate"),
      description: localize("com_ai_access.regenerate_confirmation"),
      confirmText: localize("com_ai_access.regenerate"),
    })) return;
    if (adminWideScope) {
      setAdminConfirm(true);
      setAdminAcknowledged(false);
      return;
    }
    await doIssue();
  };

  const handleDelete = async () => {
    if (busy) return;
    if (!await confirm({
      title: localize("com_ai_access.delete"),
      description: localize("com_ai_access.delete_confirmation"),
      confirmText: localize("com_ai_access.delete"),
      variant: "destructive",
    })) return;
    setAction("delete");
    setActionFailed(false);
    try {
      await deletePersonalTokenApi();
      setIssued(null);
      setStatus((previous) => previous ? { ...previous, token: null } : previous);
      showToast({ message: localize("com_ai_access.deleted_toast"), status: "success" });
    } catch {
      setActionFailed(true);
    } finally {
      setAction(null);
    }
  };

  const handleCopy = async (value: string, doneMessage?: string) => {
    try {
      await copyText(value);
      showToast({ message: doneMessage ?? localize("com_ui_copied_to_clipboard"), status: "success" });
    } catch {
      showToast({ message: localize("com_ai_access.copy_failed"), status: "error" });
    }
  };

  const handleOpenChange = (nextOpen: boolean) => {
    // While the reveal dialog is up, only it may close (defence in depth: the
    // top DismissableLayer already swallows Esc/overlay for the main dialog).
    if (!nextOpen && (action !== null || issued !== null)) return;
    if (!nextOpen) {
      setIssued(null);
      setStatus(null);
      setAdminConfirm(false);
    }
    onOpenChange(nextOpen);
  };

  const statusKey = unavailable ? "disabled"
    : token?.revoked_at ? "revoked"
      : token?.is_valid ? "active" : "expired";

  return (
    <>
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        close={false}
        className="flex h-dvh max-h-dvh w-full max-w-none flex-col gap-0 rounded-none p-0 shadow-modal min-[576px]:h-auto min-[576px]:max-h-[calc(100dvh-64px)] min-[576px]:w-[400px] min-[576px]:max-w-[calc(100vw-32px)] min-[576px]:rounded-2xl lg:w-[600px] xl:w-[960px]"
      >
        <DialogHeader className="relative shrink-0 space-y-0 px-4 py-4 pr-14 text-left">
          <DialogTitle className="text-h4 font-medium text-text-1">
            {localize(token ? "com_ai_access.title" : "com_ai_access.guide_title")}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {localize("com_ai_access.section_desc")}
          </DialogDescription>
          <TooltipAnchor description={localize("com_ui_close")} className="absolute right-4 top-3">
            <Button
              color="default" variant="text" iconOnly
              aria-label={localize("com_ui_close")}
              disabled={action !== null}
              onClick={() => handleOpenChange(false)}
            >
              <Outlined.Close />
            </Button>
          </TooltipAnchor>
        </DialogHeader>

        <div className="min-h-0 overflow-y-auto px-4 pb-6">
          {status && adminWideScope && !unavailable ? (
            <p className="mb-4 rounded-lg bg-warning-tint px-3 py-2 text-body-sm text-warning">
              {localize("com_ai_access.admin_banner", { days: String(status.ttl_days) })}
            </p>
          ) : null}
          {packOrigin ? (
            <p className="mb-4 rounded-lg bg-warning-tint px-3 py-2 text-body-sm text-warning">
              {localize("com_ai_access.address_mismatch_admin", { packOrigin, browserOrigin: window.location.origin })}
            </p>
          ) : null}
          {status && unavailable ? (
            <p className="mb-4 rounded-lg bg-fill-1 px-3 py-2 text-body-sm text-text-2">
              {localize("com_ai_access.disabled_notice")}
            </p>
          ) : null}

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <section className="flex min-w-0 flex-col gap-4">
              <h2 className="flex items-start gap-2 text-h4 font-medium text-text-1">
                <Outlined.Send className="mt-1 size-5 shrink-0 text-blue-500" aria-hidden="true" />
                {localize("com_ai_access.install_step")}
              </h2>
              <div className="flex flex-1 flex-col gap-6 rounded-2xl border border-border-base p-6">
                <p className="min-w-0 flex-1 whitespace-pre-wrap break-words text-body text-text-3">
                  {installPrompt}
                </p>
                {/* Sits right above the copy action: where to paste is decided here. */}
                <div className="flex flex-col gap-3">
                  <p className="text-body-sm text-text-2">{localize("com_ai_access.supported_note")}</p>
                  <Button color="default" variant="solid" size="large" className="self-start" onClick={() => handleCopy(installPrompt)}>
                    {localize("com_ai_access.copy_all")}
                  </Button>
                </div>
              </div>
            </section>

            <section className="flex min-w-0 flex-col gap-4" aria-busy={busy}>
              <h2 className="flex items-start gap-2 text-h4 font-medium text-text-1">
                <Outlined.Send className="mt-1 size-5 shrink-0 text-blue-500" aria-hidden="true" />
                {localize("com_ai_access.key_step")}
              </h2>
              <div className="flex flex-1 flex-col gap-6 rounded-2xl border border-border-base p-6">
                {adminConfirm ? (
                  <div className="flex flex-1 flex-col gap-3 text-body text-text-3">
                    <p className="font-medium text-text-1">{localize("com_ai_access.admin_confirm_title")}</p>
                    <p>{localize("com_ai_access.admin_confirm_body", { days: String(status?.ttl_days ?? "") })}</p>
                    <label className="flex items-start gap-2 text-body-sm">
                      <Checkbox className="mt-1" checked={adminAcknowledged} onCheckedChange={(checked) => setAdminAcknowledged(checked === true)} />
                      {localize("com_ai_access.admin_confirm_check")}
                    </label>
                    <div className="mt-2 flex flex-wrap gap-3">
                      <Button color="default" variant="outlined" size="large" onClick={() => setAdminConfirm(false)}>
                        {localize("com_ui_cancel")}
                      </Button>
                      <Button color="default" variant="solid" size="large" disabled={!adminAcknowledged || busy} loading={action === "issue"} onClick={() => void doIssue()}>
                        {localize("com_ai_access.admin_confirm_ok")}
                      </Button>
                    </div>
                  </div>
                ) : (
                <>
                <div className="flex-1 space-y-3 text-body text-text-3" aria-live="polite">
                  {loading ? <p>{localize("com_ai_access.loading")}</p> : loadFailed ? (
                    <p>{localize("com_ai_access.load_failed")}</p>
                  ) : token ? (
                    <>
                      <div className="flex min-w-0 items-center gap-2">
                        <code className="min-w-0 break-all text-text-1" aria-label={localize("com_ai_access.key_label")}>
                          {token.key_mask}
                        </code>
                        {/* Valid is the normal state; only a key that stopped working earns a status. */}
                        {statusKey === "expired" || statusKey === "revoked" ? (
                          <span className="shrink-0 rounded-md bg-danger-tint px-2 py-0.5 text-body-sm text-danger">
                            {localize(`com_ai_access.status_${statusKey}`)}
                          </span>
                        ) : null}
                      </div>
                      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-body-sm">
                        <dt>{localize("com_ai_access.expires_label")}</dt>
                        <dd className="text-text-1">{formatDate(token.expires_at)}</dd>
                        <dt>{localize("com_ai_access.last_used_label")}</dt>
                        <dd className="text-text-1">
                          {token.last_used_at ? formatDate(token.last_used_at) : localize("com_ai_access.never_used")}
                        </dd>
                      </dl>
                      {/* Only useful until the first call proves the connection. */}
                      {!token.last_used_at && statusKey === "active" ? (
                        <p className="text-body-sm">{localize("com_ai_access.verify_hint")}</p>
                      ) : null}
                    </>
                  ) : (
                    <p className="whitespace-pre-line">{localize("com_ai_access.empty_description")}</p>
                  )}
                  {status && !loading && !loadFailed ? (
                    <div className="rounded-lg bg-fill-1 px-3 py-2 text-body-sm">
                      <p>{localize("com_ai_access.scope_title")}</p>
                      <p className="mt-0.5 text-text-1">{scopeText}</p>
                    </div>
                  ) : null}
                  {actionFailed ? <p role="alert" className="text-danger">{localize("com_ai_access.action_failed")}</p> : null}
                </div>
                <div className="flex flex-wrap gap-3">
                  {loadFailed ? (
                    <Button color="default" variant="outlined" size="large" onClick={() => setReload((previous) => previous + 1)}>
                      {localize("com_ai_access.retry")}
                    </Button>
                  ) : (
                    <>
                      {/* A key that stopped working makes "get a new one" the next step. */}
                      <Button color="default" variant={token && statusKey === "active" ? "filled" : "solid"} size="large" loading={action === "issue"} disabled={busy || unavailable} onClick={handleIssue}>
                        {localize(token ? "com_ai_access.regenerate" : "com_ai_access.get_key")}
                      </Button>
                      {token ? (
                        <Button color="danger" variant="text" size="large" loading={action === "delete"} disabled={busy} onClick={handleDelete}>
                          {localize("com_ai_access.delete")}
                        </Button>
                      ) : null}
                    </>
                  )}
                </div>
                </>
                )}
              </div>
            </section>
          </div>
        </div>
      </DialogContent>
    </Dialog>
    <TokenRevealDialog issued={issued} baseUrl={window.location.origin} onClose={() => setIssued(null)} onCopy={handleCopy} />
    </>
  );
}
