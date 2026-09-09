import { useEffect, useState } from "react";
import {
  deletePersonalTokenApi,
  getPersonalTokenInstallPromptApi,
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
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "~/components/ui";
import { useToastContext } from "~/Providers/ToastContext";
import { useLocalize } from "~/hooks";
import { copyText } from "~/utils";

export interface PersonalTokenDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function formatDate(value: string | null, fallback: string): string {
  return value ? new Date(value).toLocaleString() : fallback;
}

export function PersonalTokenDialog({ open, onOpenChange }: PersonalTokenDialogProps) {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const [status, setStatus] = useState<PersonalTokenStatus | null>(null);
  const [issued, setIssued] = useState<PersonalTokenIssued | null>(null);
  const [saved, setSaved] = useState(false);
  const [loading, setLoading] = useState(false);

  const loadStatus = async () => {
    setStatus(await getPersonalTokenStatusApi());
  };

  useEffect(() => {
    if (!open) return;
    setIssued(null);
    setSaved(false);
    setLoading(true);
    loadStatus().finally(() => setLoading(false));
  }, [open]);

  const notifySuccess = () => {
    showToast({ message: localize("com_personal_token_operation_success"), status: "success" });
  };

  const handleIssue = async () => {
    setLoading(true);
    try {
      const next = await issuePersonalTokenApi();
      setIssued(next);
      setSaved(false);
      await loadStatus();
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    setLoading(true);
    try {
      await deletePersonalTokenApi();
      setIssued(null);
      setSaved(false);
      await loadStatus();
      notifySuccess();
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = async (value: string) => {
    await copyText(value);
    showToast({ message: localize("com_ui_copied_to_clipboard"), status: "success" });
  };

  const handleCopyInstallPrompt = async () => {
    const prompt = await getPersonalTokenInstallPromptApi();
    await handleCopy(prompt.prompt);
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen && issued && !saved) return;
    onOpenChange(nextOpen);
  };

  const token = status?.token;
  const unavailable = status !== null && !status.enabled;
  const fallback = localize("com_personal_token_never");

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent close={!issued || saved} className="w-[calc(100%-32px)] sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{localize("com_personal_token_title")}</DialogTitle>
          <DialogDescription>{localize("com_personal_token_description")}</DialogDescription>
        </DialogHeader>

        {status?.holder_is_admin ? (
          <p className="rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">
            {localize("com_personal_token_admin_warning")}
          </p>
        ) : null}

        {unavailable ? (
          <p className="rounded-lg bg-fill-1 px-3 py-2 text-sm text-text-2">
            {localize("com_personal_token_disabled")}
          </p>
        ) : null}

        {issued ? (
          <section className="space-y-3">
            <p className="text-sm text-text-1">{localize("com_personal_token_once")}</p>
            <div className="flex items-center gap-2 rounded-lg bg-fill-1 p-3">
              <code className="min-w-0 flex-1 break-all text-sm">{issued.plaintext}</code>
              <Button variant="outline" onClick={() => handleCopy(issued.plaintext)}>
                {localize("com_personal_token_copy")}
              </Button>
            </div>
            <label className="flex items-center gap-2 text-sm text-text-1">
              <Checkbox checked={saved} onCheckedChange={(checked) => setSaved(checked === true)} />
              {localize("com_personal_token_saved_confirmation")}
            </label>
          </section>
        ) : token ? (
          <section className="space-y-2 rounded-lg border border-fill-2 p-4 text-sm">
            <p><span className="text-text-3">{localize("com_personal_token_mask")}: </span>{token.key_mask}</p>
            <p><span className="text-text-3">{localize("com_personal_token_scope")}: </span>{token.scopes.join(", ")}</p>
            <p><span className="text-text-3">{localize("com_personal_token_expires")}: </span>{formatDate(token.expires_at, fallback)}</p>
            <p><span className="text-text-3">{localize("com_personal_token_last_used")}: </span>{formatDate(token.last_used_at, fallback)}</p>
          </section>
        ) : (
          <p className="py-5 text-center text-sm text-text-3">
            {loading ? localize("com_personal_token_loading") : localize("com_personal_token_empty")}
          </p>
        )}

        <DialogFooter className="gap-2 sm:space-x-0">
          {!issued ? (
            <Button variant="outline" disabled={loading || unavailable} onClick={handleCopyInstallPrompt}>
              {localize("com_personal_token_copy_install_prompt")}
            </Button>
          ) : null}
          {token && !issued ? (
            <Button color="danger" variant="outline" disabled={loading} onClick={handleDelete}>
              {localize("com_personal_token_delete")}
            </Button>
          ) : null}
          {!issued ? (
            <Button disabled={loading || unavailable} onClick={handleIssue}>
              {localize(token ? "com_personal_token_regenerate" : "com_personal_token_create")}
            </Button>
          ) : (
            <Button disabled={!saved} onClick={() => handleOpenChange(false)}>
              {localize("com_personal_token_done")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
