import { Button, Input, toast } from "@bisheng/ui";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog";
import { importKnowledgeWebLinkApi } from "@/controllers/API";

const WEB_LINK_DUPLICATE_ERROR_CODES = new Set([18021, 18023]);

const WEB_LINK_ERROR_KEY_MAP: Record<string, string> = {
  "web link redirect location is missing": "webLinkRequestFailed",
  "web link content type is not supported": "webLinkContentTypeUnsupported",
  "web link content is too large": "webLinkContentTooLarge",
  "web link redirects too many times": "webLinkRedirectsTooMany",
  "web link content is empty": "webLinkContentEmpty",
  "web link url is empty": "webLinkUrlRequired",
  "only http/https web links are supported": "webLinkHttpOnly",
  "web link host is missing": "webLinkInvalid",
  "this web link host is not allowed": "webLinkHostNotAllowed",
  "this web link address is not allowed": "webLinkAddressNotAllowed",
  "web link host cannot be resolved": "webLinkHostUnresolved",
  "target site refused server-side access": "webLinkAccessRefused",
  "target site requires authentication": "webLinkAuthRequired",
  "target site rate limited server-side access": "webLinkRateLimited",
  "media file does not exist": "mediaFileMissing",
  "asr returned empty text": "mediaAsrEmpty",
  "no recognizable audio detected": "mediaNoRecognizableAudio",
  "asr api key is missing": "mediaAsrApiKeyMissing",
  "ffmpeg is not installed": "mediaFfmpegMissing",
  "media audio extraction failed": "mediaAudioExtractionFailed",
};

function normalizeWebLinkTitle(title: string): string | undefined {
  const trimmed = title.trim();
  if (!trimmed) return undefined;
  return /\.html$/i.test(trimmed) ? trimmed : `${trimmed}.html`;
}

interface WebLinkImportDialogProps {
  knowledgeId?: string;
  parentId?: number | null;
  scopeKey?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImported?: () => void;
}
type WebError = {
  status_code?: unknown;
  statusCode?: unknown;
  status_message?: unknown;
  message?: unknown;
  data?: Record<string, unknown>;
};
const errorFacts = (cause: unknown): WebError =>
  cause && typeof cause === "object" ? (cause as WebError) : {};
export default function WebLinkImportDialog(props: WebLinkImportDialogProps) {
  return props.open ? (
    <WebLinkOpening
      key={JSON.stringify([props.scopeKey, props.knowledgeId, props.parentId])}
      {...props}
    />
  ) : null;
}
function WebLinkOpening({
  knowledgeId,
  parentId,
  onOpenChange,
  onImported,
}: WebLinkImportDialogProps) {
  const { t } = useTranslation("knowledge");
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [loading, setLoading] = useState(false);
  const lifetime = useRef<{ active: boolean; controller: AbortController }>({
    active: true,
    controller: new AbortController(),
  });
  useEffect(() => {
    const opening = lifetime.current.controller.signal.aborted
      ? { active: true, controller: new AbortController() }
      : lifetime.current;
    lifetime.current = opening;
    return () => {
      opening.active = false;
      opening.controller.abort();
    };
  }, []);
  const live = () => lifetime.current.active;
  const resolveErrorMessage = (cause: unknown, fallback: string) => {
    const error = errorFacts(cause);
    const code = error.status_code ?? error.statusCode;
    const message =
      typeof error.status_message === "string"
        ? error.status_message.toLowerCase()
        : typeof error.message === "string"
          ? error.message.toLowerCase()
          : "";
    const mapped =
      WEB_LINK_ERROR_KEY_MAP[message] ??
      (message.startsWith("web link request failed")
        ? "webLinkRequestFailed"
        : message.startsWith("knowledge media transcription only supports aliyun/qwen asr") ||
            message.startsWith("knowledge media transcription does not support asr provider")
          ? "mediaAsrProviderUnsupported"
          : message.startsWith("asr request failed")
            ? "mediaAsrRequestFailed"
            : undefined);
    if (mapped) return t(mapped);
    if (code != null) {
      const translated = t(`api_errors:${code}`, {
        ...error.data,
        defaultValue: "",
      });
      if (translated) return translated;
    }
    return t(fallback);
  };
  const submit = async () => {
    if (loading || !live()) return;
    const normalized = url.trim();
    if (!knowledgeId) {
      toast.show({ type: "warning", message: t("knowledgeIdMissing") });
      return;
    }
    if (!normalized) {
      toast.show({ type: "warning", message: t("webLinkUrlRequired") });
      return;
    }
    try {
      if (!["http:", "https:"].includes(new URL(normalized).protocol)) {
        toast.show({ type: "warning", message: t("webLinkHttpOnly") });
        return;
      }
    } catch {
      toast.show({ type: "warning", message: t("webLinkInvalid") });
      return;
    }
    const command = {
      url: normalized,
      title: normalizeWebLinkTitle(title),
      ...(parentId === undefined ? {} : { parent_id: parentId }),
    };
    const perform = async (overwrite = false) => {
      if (!live()) return;
      setLoading(true);
      try {
        await importKnowledgeWebLinkApi(
          knowledgeId,
          { ...command, ...(overwrite ? { overwrite: true } : {}) },
          lifetime.current.controller.signal,
        );
        if (!live()) return;
        toast.show({ type: "success", message: t("webLinkImportStarted") });
        onImported?.();
        onOpenChange(false);
      } finally {
        if (live()) setLoading(false);
      }
    };
    try {
      await perform();
    } catch (error) {
      if (!live()) return;
      if (WEB_LINK_DUPLICATE_ERROR_CODES.has(Number(errorFacts(error).status_code))) {
        bsConfirm({
          title: t("duplicateWebLinkTitle"),
          desc: command.title || command.url,
          signal: lifetime.current.controller.signal,
          canelTxt: t("cancel"),
          okTxt: t("overwrite"),
          onCancel: () => {
            if (live()) onOpenChange(false);
          },
          onOk: async (close) => {
            if (!live()) {
              close();
              return;
            }
            try {
              await perform(true);
              if (live()) close();
            } catch (cause) {
              if (live())
                toast.show({
                  type: "error",
                  message: resolveErrorMessage(cause, "webLinkOverwriteFailed"),
                });
            }
          },
        });
      } else
        toast.show({
          type: "error",
          message: resolveErrorMessage(error, "webLinkImportFailed"),
        });
    }
  };
  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next && !loading) onOpenChange(false);
      }}
    >
      <DialogContent
        className="max-w-[520px]"
        aria-describedby={undefined}
        onEscapeKeyDown={(event) => {
          if (loading) event.preventDefault();
        }}
        onPointerDownOutside={(event) => {
          if (loading) event.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle>{t("webLink")}</DialogTitle>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <label className="block space-y-2 text-body-sm text-text-1">
            <span className="font-medium">{t("webLinkUrl")}</span>
            <Input
              value={url}
              onChange={(event) => setUrl(event.currentTarget.value)}
              placeholder="https://example.com/page"
              disabled={loading}
            />
          </label>
          <label className="block space-y-2 text-body-sm text-text-1">
            <span className="font-medium">{t("webLinkTitle")}</span>
            <Input
              value={title}
              onChange={(event) => setTitle(event.currentTarget.value)}
              placeholder={t("webLinkTitlePlaceholder")}
              disabled={loading}
            />
          </label>
          <DialogFooter>
            <Button
              type="button"
              variant="outlined"
              onClick={() => onOpenChange(false)}
              disabled={loading}
              color="default"
            >
              {t("cancel")}
            </Button>
            <Button type="submit" loading={loading}>
              {t("import")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
