import { Button, Checkbox, notification } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog";
import type { KunlianApiKeyIssued } from "@/types/api/kunlianApiKey";
import { copyText } from "@/utils";
import { buildKunlianVerifyCommand } from "./utils";

export interface KeyRevealDialogProps {
  issuedKey: KunlianApiKeyIssued | null;
  onClose: () => void;
}

export function KeyRevealDialog({ issuedKey, onClose }: KeyRevealDialogProps) {
  const { t } = useTranslation();
  const [saved, setSaved] = useState(false);
  const [verifyOpen, setVerifyOpen] = useState(false);

  useEffect(() => {
    if (issuedKey) {
      setSaved(false);
      setVerifyOpen(false);
    }
  }, [issuedKey]);

  const plaintext = issuedKey?.api_key || "";
  const verifyCommand = issuedKey
    ? buildKunlianVerifyCommand(location.origin, issuedKey.api_key)
    : "";

  const handleCopy = (value: string) => {
    copyText(value);
    notification.open({
      type: "success",
      title: String(t("kunlianApiKey.reveal.title") ?? ""),
      description: String(t("kunlianApiKey.feedback.copied") ?? ""),
    });
  };

  const handleClose = () => {
    if (!saved) return;
    onClose();
  };

  return (
    <Dialog
      open={!!issuedKey}
      onOpenChange={(nextOpen) => !nextOpen && handleClose()}
    >
      <DialogContent className="sm:max-w-[600px] [&>button]:hidden">
        <DialogHeader>
          <DialogTitle>{t("kunlianApiKey.reveal.title")}</DialogTitle>
        </DialogHeader>
        <div className="min-w-0 space-y-4 py-2">
          <p className="text-sm text-destructive">
            {t("kunlianApiKey.reveal.onceHint")}
          </p>
          <div className="flex items-center gap-2 rounded-md border bg-muted/40 p-3">
            <code className="min-w-0 flex-1 break-all font-mono text-sm">
              {plaintext}
            </code>
            <Button
              type="button"
              variant="outlined"
              size="small"
              color="default"
              onClick={() => handleCopy(plaintext)}
            >
              <Outlined.Copy aria-hidden="true" className="mr-1 size-3.5" />
              {t("kunlianApiKey.actions.copy")}
            </Button>
          </div>
          <div>
            <Button
              type="button"
              variant="text"
              size="small"
              color="default"
              aria-expanded={verifyOpen}
              className="flex items-center gap-1 rounded-sm text-sm text-muted-foreground hover:text-foreground"
              onClick={() => setVerifyOpen((current) => !current)}
            >
              <Outlined.Right
                aria-hidden="true"
                className={`size-4 transition-transform ${verifyOpen ? "rotate-90" : ""}`}
              />
              {t("kunlianApiKey.reveal.verifyTitle")}
            </Button>
            {verifyOpen ? (
              <div className="mt-2 space-y-2 pl-5">
                <p className="text-xs text-muted-foreground">
                  {t("kunlianApiKey.reveal.verifyHint")}
                </p>
                <div className="relative rounded-md border bg-muted/40">
                  <pre className="whitespace-pre-wrap break-all p-3 pr-12 font-mono text-xs leading-5">
                    {verifyCommand}
                  </pre>
                  <Button
                    type="button"
                    variant="text"
                    size="medium"
                    color="default"
                    iconOnly
                    className="absolute right-1.5 top-1.5 size-7"
                    aria-label={t("kunlianApiKey.actions.copy")}
                    onClick={() => handleCopy(verifyCommand)}
                  >
                    <Outlined.Copy aria-hidden="true" className="size-3.5" />
                  </Button>
                </div>
              </div>
            ) : null}
          </div>
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <Checkbox
              checked={saved}
              onCheckedChange={(checked) => setSaved(checked === true)}
            />
            {t("kunlianApiKey.reveal.savedConfirm")}
          </label>
        </div>
        <DialogFooter>
          <Button disabled={!saved} onClick={handleClose}>
            {t("confirmButton")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
