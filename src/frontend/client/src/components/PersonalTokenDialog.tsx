import { Outlined } from "bisheng-icons";
import { useEffect, useState } from "react";
import {
  deletePersonalTokenApi,
  getPersonalTokenGuideUrls,
  getPersonalTokenStatusApi,
  issuePersonalTokenApi,
  type PersonalTokenIssued,
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

export function PersonalTokenDialog({ open, onOpenChange }: PersonalTokenDialogProps) {
  const localize = useLocalize();
  const confirm = useConfirm();
  const { showToast } = useToastContext();
  const [status, setStatus] = useState<PersonalTokenStatus | null>(null);
  const [issued, setIssued] = useState<PersonalTokenIssued | null>(null);
  const [saved, setSaved] = useState(false);
  const [loading, setLoading] = useState(false);
  const [action, setAction] = useState<"issue" | "delete" | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [reload, setReload] = useState(0);
  const [actionFailed, setActionFailed] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setStatus(null);
    setIssued(null);
    setSaved(false);
    setLoadFailed(false);
    setActionFailed(false);
    setLoading(true);
    getPersonalTokenStatusApi()
      .then((next) => { if (!cancelled) setStatus(next); })
      .catch(() => { if (!cancelled) setLoadFailed(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [open, reload]);

  const token = issued ?? status?.token;
  const unavailable = !status?.enabled;
  const busy = loading || action !== null;
  const unsaved = issued !== null && !saved;
  const urls = getPersonalTokenGuideUrls(window.location.origin);
  const installPrompt = localize("com_personal_token.install_prompt", urls);
  const requestBody = JSON.stringify({
    query: localize("com_personal_token.example_query"),
    knowledge_base_ids: [1],
  });
  const example = [
    `curl -X POST '${urls.retrieveUrl}' \\`,
    '  -H "Authorization: Bearer $BISHENG_API_KEY" \\',
    "  -H 'Content-Type: application/json' \\",
    `  -d '${requestBody}'`,
  ].join("\n");

  const handleIssue = async () => {
    if (busy || unavailable || unsaved) return;
    if (token && !await confirm({
      title: localize("com_personal_token.regenerate"),
      description: localize("com_personal_token.regenerate_confirmation"),
      confirmText: localize("com_personal_token.regenerate"),
    })) return;
    setAction("issue");
    setActionFailed(false);
    try {
      const next = await issuePersonalTokenApi();
      setIssued(next);
      setSaved(false);
      setStatus((previous) => previous ? { ...previous, token: next } : previous);
    } catch {
      setActionFailed(true);
    } finally {
      setAction(null);
    }
  };

  const handleDelete = async () => {
    if (busy || unsaved) return;
    if (!await confirm({
      title: localize("com_personal_token.delete"),
      description: localize("com_personal_token.delete_confirmation"),
      confirmText: localize("com_personal_token.delete"),
      variant: "destructive",
    })) return;
    setAction("delete");
    setActionFailed(false);
    try {
      await deletePersonalTokenApi();
      setIssued(null);
      setSaved(false);
      setStatus((previous) => previous ? { ...previous, token: null } : previous);
      showToast({ message: localize("com_personal_token_operation_success"), status: "success" });
    } catch {
      setActionFailed(true);
    } finally {
      setAction(null);
    }
  };

  const handleCopy = async (value: string) => {
    try {
      await copyText(value);
      showToast({ message: localize("com_ui_copied_to_clipboard"), status: "success" });
    } catch {
      showToast({ message: localize("com_personal_token.copy_failed"), status: "error" });
    }
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen && (action !== null || unsaved)) return;
    if (!nextOpen) {
      setIssued(null);
      setStatus(null);
    }
    onOpenChange(nextOpen);
  };

  const statusKey = unavailable ? "disabled"
    : token?.revoked_at ? "revoked"
      : token?.is_valid ? "active" : "expired";

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        close={false}
        className="flex h-dvh max-h-dvh w-full max-w-none flex-col gap-0 rounded-none p-0 shadow-modal min-[576px]:h-auto min-[576px]:max-h-[calc(100dvh-64px)] min-[576px]:w-[400px] min-[576px]:max-w-[calc(100vw-32px)] min-[576px]:rounded-2xl lg:w-[600px] xl:w-[960px]"
      >
        <DialogHeader className="relative shrink-0 space-y-0 px-4 py-4 pr-14 text-left">
          <DialogTitle className="text-h4 font-medium text-text-1">
            {localize("com_personal_token.guide_title")}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {localize("com_personal_token_description")}
          </DialogDescription>
          <TooltipAnchor description={localize("com_ui_close")} className="absolute right-4 top-3">
            <Button
              color="default" variant="text" iconOnly
              aria-label={localize("com_ui_close")}
              disabled={action !== null || unsaved}
              onClick={() => handleOpenChange(false)}
            >
              <Outlined.Close />
            </Button>
          </TooltipAnchor>
        </DialogHeader>

        <div className="min-h-0 overflow-y-auto px-4 pb-6">
          {status?.holder_is_admin ? (
            <p className="mb-4 rounded-lg bg-warning-soft px-3 py-2 text-body-sm text-warning">
              {localize("com_personal_token_admin_warning")}
            </p>
          ) : null}
          {status && unavailable ? (
            <p className="mb-4 rounded-lg bg-fill-1 px-3 py-2 text-body-sm text-text-2">
              {localize("com_personal_token_disabled")}
            </p>
          ) : null}

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <section className="flex min-w-0 flex-col gap-4">
              <h2 className="flex items-start gap-2 text-h4 font-medium text-text-1">
                <Outlined.Send className="mt-1 size-5 shrink-0 text-blue-500" aria-hidden="true" />
                {localize("com_personal_token.install_step")}
              </h2>
              <div className="flex flex-1 flex-col gap-8 rounded-2xl border border-border-base p-6">
                <p className="min-w-0 flex-1 whitespace-pre-wrap break-words text-body text-text-3">
                  {installPrompt}
                </p>
                <Button color="default" variant="solid" size="large" className="self-start" onClick={() => handleCopy(installPrompt)}>
                  {localize("com_personal_token.copy_all")}
                </Button>
              </div>
            </section>

            <section className="flex min-w-0 flex-col gap-4" aria-busy={busy}>
              <h2 className="flex items-start gap-2 text-h4 font-medium text-text-1">
                <Outlined.Send className="mt-1 size-5 shrink-0 text-blue-500" aria-hidden="true" />
                {localize("com_personal_token.key_step")}
              </h2>
              <div className="flex flex-1 flex-col gap-8 rounded-2xl border border-border-base p-6">
                <div className="flex-1 space-y-3 text-body text-text-3" aria-live="polite">
                  {loading ? <p>{localize("com_personal_token_loading")}</p> : loadFailed ? (
                    <p>{localize("com_personal_token.load_failed")}</p>
                  ) : token ? (
                    <>
                      <div className="flex items-start gap-2">
                        <p className="min-w-0 flex-1 break-all">
                          <span>{localize("com_personal_token.key_label")}: </span>
                          <code>{issued?.plaintext ?? token.key_mask}</code>
                        </p>
                        {issued ? (
                          <TooltipAnchor description={localize("com_personal_token.copy_key")}>
                            <Button color="default" variant="text" iconOnly aria-label={localize("com_personal_token.copy_key")} onClick={() => handleCopy(issued.plaintext)}>
                              <Outlined.Copy />
                            </Button>
                          </TooltipAnchor>
                        ) : null}
                      </div>
                      <p>{localize("com_personal_token.status_label")}: {localize(`com_personal_token.status_${statusKey}`)}</p>
                      <p>{localize("com_personal_token.expires_label")}: {formatDate(token.expires_at)}</p>
                      <p>{localize("com_personal_token.created_label")}: {formatDate(token.create_time)}</p>
                      <p>{localize("com_personal_token_last_used")}: {formatDate(token.last_used_at)}</p>
                      {issued ? (
                        <div className="space-y-3 text-body-sm text-text-2">
                          <p>{localize("com_personal_token_once")}</p>
                          <label className="flex items-start gap-2">
                            <Checkbox className="mt-1" checked={saved} onCheckedChange={(checked) => setSaved(checked === true)} />
                            {localize("com_personal_token_saved_confirmation")}
                          </label>
                        </div>
                      ) : <p className="text-body-sm">{localize("com_personal_token.masked_hint")}</p>}
                    </>
                  ) : (
                    <p className="whitespace-pre-line">{localize("com_personal_token.empty_description")}</p>
                  )}
                  {actionFailed ? <p role="alert" className="text-danger">{localize("com_personal_token.action_failed")}</p> : null}
                </div>
                <div className="flex flex-wrap gap-3">
                  {loadFailed ? (
                    <Button color="default" variant="outlined" size="large" onClick={() => setReload((previous) => previous + 1)}>
                      {localize("com_personal_token.retry")}
                    </Button>
                  ) : (
                    <>
                      {token ? (
                        <Button color="danger" variant="filled" size="large" loading={action === "delete"} disabled={busy || unsaved} onClick={handleDelete}>
                          {localize("com_personal_token.delete")}
                        </Button>
                      ) : null}
                      <Button color="default" variant={token ? "filled" : "solid"} size="large" loading={action === "issue"} disabled={busy || unavailable || unsaved} onClick={handleIssue}>
                        {localize(token ? "com_personal_token.regenerate" : "com_personal_token.get_key")}
                      </Button>
                    </>
                  )}
                </div>
              </div>
            </section>
          </div>

          <details className="mt-5 text-body-sm text-text-3">
            <summary className="cursor-pointer text-blue-500">{localize("com_personal_token.developer_guide")}</summary>
            <p className="my-3">{localize("com_personal_token.example_hint")}</p>
            <pre className="overflow-x-auto rounded-xl bg-fill-1 p-4 text-body-sm text-text-2"><code>{example}</code></pre>
            <Button color="default" variant="outlined" className="mt-3" onClick={() => handleCopy(example)}>
              {localize("com_personal_token.copy_example")}
            </Button>
          </details>
        </div>
      </DialogContent>
    </Dialog>
  );
}
