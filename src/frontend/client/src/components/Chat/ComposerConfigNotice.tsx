import { Alert } from "@bisheng/ui";
import { isApiError } from "@bisheng/api-client";
import { showApiError } from "~/api/request";
import useLocalize from "~/hooks/useLocalize";

interface ComposerConfigNoticeProps {
  /** Failure of the workstation config request, if it failed. */
  error: unknown;
  /** True once the workstation config request has succeeded. */
  loaded: boolean;
  hasModels: boolean;
  onRetry: () => unknown;
}

/**
 * Says why the composer is disabled when the workstation config is unusable.
 *
 * The composer is disabled without a model list. Before this notice a failed
 * config request, or a config with no model, left a dead input and no words.
 */
export function ComposerConfigNotice({
  error,
  loaded,
  hasModels,
  onRetry,
}: ComposerConfigNoticeProps) {
  const localize = useLocalize();
  // A background refresh can fail while an earlier config still serves the
  // composer; with models on hand the input works and needs no notice.
  if (hasModels) return null;
  if (error && !(isApiError(error) && error.kind === "canceled")) {
    return (
      <Alert
        type="error"
        live
        description={localize("dshChat.configLoadFailed")}
        actions={[
          {
            label: localize("com_ui_retry"),
            onClick: () => {
              void Promise.resolve().then(onRetry).catch(showApiError);
            },
          },
        ]}
      />
    );
  }
  if (loaded) {
    return (
      <Alert type="warning" description={localize("dshChat.noModelsConfigured")} />
    );
  }
  return null;
}
