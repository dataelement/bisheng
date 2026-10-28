import "@/style/dsh-content-safety.css";
import { isDshSensitivePolicyConflict } from "@/controllers/API/dshContentSafety";
import type {
  DshSensitivePolicy,
  DshSensitivePolicyCommand,
} from "@/types/dshContentSafety";
import { Button, Checkbox, CheckboxGroup, Textarea } from "@bisheng/ui";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  dshSensitivePolicyValidationError,
  useDshContentSafety,
  validateDshSensitivePolicy,
} from "./useDshContentSafety";

interface DshContentSafetySettingsProps {
  tenantId?: number;
  canConfigure: boolean;
}

function draftOf(policy: DshSensitivePolicy): DshSensitivePolicyCommand {
  return {
    expected_version: policy.version,
    enabled: policy.enabled,
    input_enabled: policy.input_enabled,
    output_enabled: policy.output_enabled,
    words_types: [...policy.words_types],
    custom_words: policy.custom_words,
    auto_reply: policy.auto_reply,
  };
}

export function DshContentSafetySettings(props: DshContentSafetySettingsProps) {
  const [client] = useState(() => new QueryClient({
    // Transport errors can contain policy drafts and credential-bearing request configs.
    logger: { log: () => {}, warn: () => {}, error: () => {} },
  }));
  return (
    <div className="dsh-content-safety">
      <QueryClientProvider client={client}>
        <DshContentSafetyForm key={props.tenantId ?? "no-tenant"} {...props} />
      </QueryClientProvider>
    </div>
  );
}

function DshContentSafetyForm({
  tenantId,
  canConfigure,
}: DshContentSafetySettingsProps) {
  const { t } = useTranslation();
  const controls = useDshContentSafety(tenantId);
  const hasTenant = Number.isSafeInteger(tenantId) && Number(tenantId) > 0;
  const [draft, setDraft] = useState<DshSensitivePolicyCommand | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const locked = useRef(false);
  const id = useId();
  const snapshot = controls.policy.data;
  useEffect(() => {
    if (snapshot && draft === null) setDraft(draftOf(snapshot));
  }, [snapshot, draft]);
  const limits = snapshot?.limits ?? controls.capabilities.data?.limits;
  const validation = useMemo(
    () => (draft && limits ? validateDshSensitivePolicy(draft, limits) : null),
    [draft, limits],
  );
  const dirty =
    !!draft &&
    !!snapshot &&
    JSON.stringify(draft) !== JSON.stringify(draftOf(snapshot));
  const busy = controls.mutation.isLoading || refreshing;
  const disabled = !canConfigure || busy || !controls.ready;
  const handleChange = (changes: Partial<DshSensitivePolicyCommand>) => {
    if (disabled || locked.current) return;
    setDraft((old) => (old ? { ...old, ...changes } : old));
    setFeedback(null);
  };
  async function handleRefresh() {
    if (locked.current) return;
    locked.current = true;
    setRefreshing(true);
    try {
      const latest = await controls.refresh();
      if (!latest) {
        setFeedback("errors.load_failed");
        return;
      }
      setDraft((old) =>
        old && (dirty || conflict)
          ? { ...old, expected_version: latest.version }
          : draftOf(latest),
      );
      setConflict(false);
      setFeedback(null);
    } finally {
      locked.current = false;
      setRefreshing(false);
    }
  }
  async function handleSave() {
    if (
      locked.current ||
      disabled ||
      !draft ||
      validation ||
      conflict ||
      !dirty
    )
      return;
    locked.current = true;
    setFeedback(null);
    try {
      const saved = await controls.mutation.mutateAsync(draft);
      setDraft(draftOf(saved));
      setFeedback("actions.saved");
    } catch (error) {
      if (isDshSensitivePolicyConflict(error)) {
        setConflict(true);
        setFeedback("errors.version_conflict");
      } else {
        const invalid = dshSensitivePolicyValidationError(error);
        setFeedback(invalid ? "validation." + invalid : "errors.save_failed");
      }
    } finally {
      locked.current = false;
    }
  }
  const showRefresh =
    hasTenant &&
    !controls.capabilities.isLoading &&
    (!controls.ready ||
      controls.policy.isError ||
      conflict ||
      feedback === "errors.load_failed");
  const capabilityError =
    controls.capabilities.isError || !controls.capabilities.data
      ? "errors.capabilities_unknown"
      : !controls.capabilities.data.enabled
        ? "errors.deployment_disabled"
        : "errors.unavailable";
  return (
    <section
      className="space-y-4 rounded-lg border p-4"
      aria-labelledby={id + "-title"}
    >
      <header className="space-y-1">
        <h3 id={id + "-title"} className="text-sm font-medium">
          {t("dsh.contentSafety.title")}
        </h3>
      </header>
      {!hasTenant ? (
        <p role="status">{t("dsh.modelAuditView.selectTenant")}</p>
      ) : controls.capabilities.isLoading ? (
        <p role="status">{t("dsh.loading")}</p>
      ) : !controls.ready ? (
        <p role="alert">{t("dsh.contentSafety." + capabilityError)}</p>
      ) : controls.policy.isError && !draft ? (
        <p role="alert">{t("dsh.contentSafety.errors.load_failed")}</p>
      ) : !draft || !snapshot ? (
        <p role="status">{t("dsh.loading")}</p>
      ) : (
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            void handleSave();
          }}
        >
          <fieldset disabled={disabled} className="space-y-4">
            <Checkbox
              disabled={disabled}
              label={t("dsh.contentSafety.settings.enabled")}
              checked={draft.enabled}
              onCheckedChange={(checked) =>
                handleChange({ enabled: checked === true })
              }
            />
            <CheckboxGroup
              direction="vertical"
              aria-label={t("dsh.contentSafety.filters.direction")}
            >
              <Checkbox
                disabled={disabled}
                label={t("dsh.contentSafety.settings.input_enabled")}
                checked={draft.input_enabled}
                onCheckedChange={(checked) =>
                  handleChange({ input_enabled: checked === true })
                }
              />
              <Checkbox
                disabled={disabled}
                label={t("dsh.contentSafety.settings.output_enabled")}
                checked={draft.output_enabled}
                onCheckedChange={(checked) =>
                  handleChange({ output_enabled: checked === true })
                }
              />
            </CheckboxGroup>
            <div className="space-y-2">
              <p className="text-sm font-medium">
                {t("dsh.contentSafety.settings.word_sources")}
              </p>
              <CheckboxGroup
                direction="vertical"
                aria-label={t("dsh.contentSafety.settings.word_sources")}
              >
                {(["1", "2"] as const).map((source) => (
                  <Checkbox
                    disabled={disabled}
                    key={source}
                    label={t(
                      "dsh.contentSafety.settings." +
                        (source === "1" ? "builtin_words" : "custom_words"),
                    )}
                    checked={draft.words_types.includes(source)}
                    onCheckedChange={(checked) =>
                      handleChange({
                        words_types:
                          checked === true
                            ? [...new Set([...draft.words_types, source])]
                            : draft.words_types.filter(
                                (value) => value !== source,
                              ),
                      })
                    }
                  />
                ))}
              </CheckboxGroup>
            </div>
            <div className="space-y-1">
              <label htmlFor={id + "-words"} className="text-sm">
                {t("dsh.contentSafety.settings.custom_words")}
              </label>
              <Textarea
                id={id + "-words"}
                value={draft.custom_words}
                rows={6}
                disabled={disabled || !draft.words_types.includes("2")}
                aria-describedby={id + "-words-hint"}
                onChange={(event) =>
                  handleChange({ custom_words: event.target.value })
                }
              />
              <span
                id={id + "-words-hint"}
                className="block text-sm text-muted-foreground"
              >
                {t("dsh.contentSafety.settings.custom_words_hint")}
              </span>
            </div>
            <div className="space-y-1">
              <label htmlFor={id + "-reply"} className="text-sm">
                {t("dsh.contentSafety.settings.auto_reply")}
              </label>
              <Textarea
                id={id + "-reply"}
                value={draft.auto_reply}
                disabled={disabled}
                aria-describedby={id + "-reply-hint"}
                onChange={(event) =>
                  handleChange({ auto_reply: event.target.value })
                }
              />
              <span
                id={id + "-reply-hint"}
                className="block text-sm text-muted-foreground"
              >
                {t("dsh.contentSafety.settings.auto_reply_hint")}
              </span>
            </div>
          </fieldset>
          {validation && (
            <p role="alert" className="text-sm text-destructive">
              {t("dsh.contentSafety.validation." + validation)}
            </p>
          )}
          {!draft.enabled && (
            <p className="text-sm text-muted-foreground">
              {t(
                snapshot.version === 0
                  ? "dsh.contentSafety.settings.default_off"
                  : "dsh.contentSafety.settings.disabled_hint",
              )}
            </p>
          )}
          {canConfigure && (
            <Button
              type="submit"
              color="primary"
              variant="solid"
              loading={controls.mutation.isLoading}
              disabled={disabled || !dirty || !!validation || conflict}
            >
              {t(
                "dsh.contentSafety.actions." +
                  (controls.mutation.isLoading ? "saving" : "save"),
              )}
            </Button>
          )}
        </form>
      )}
      {feedback && (feedback !== "errors.load_failed" || (controls.ready && !!draft)) && (
        <p
          role={feedback === "actions.saved" ? "status" : "alert"}
          className="text-sm"
        >
          {t("dsh.contentSafety." + feedback)}
        </p>
      )}
      {conflict && feedback !== "errors.version_conflict" && (
        <p role="alert" className="text-sm">
          {t("dsh.contentSafety.errors.version_conflict")}
        </p>
      )}
      {showRefresh && (
        <Button
          type="button"
          variant="outlined"
          disabled={busy}
          loading={refreshing}
          onClick={() => void handleRefresh()}
        >
          {t("dsh.contentSafety.actions.refresh")}
        </Button>
      )}
    </section>
  );
}
