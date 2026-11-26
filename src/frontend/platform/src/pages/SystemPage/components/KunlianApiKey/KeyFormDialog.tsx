import { Button, Checkbox, Input, notification } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { DatePicker } from "@/components/bs-ui/calendar/datePicker";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog";
import { Label } from "@/components/bs-ui/label";
import {
  getKunlianIntegrationStatusSilentApi,
  getKunlianTenantsSilentApi,
  issueKunlianApiKeyApi,
  updateKunlianApiKeyApi,
} from "@/controllers/API/kunlianApiKeys";
import { showApiError } from "@/controllers/request";
import {
  KUNLIAN_ALL_TENANTS_WILDCARD,
  KUNLIAN_API_KEY_CAPABILITIES,
  type KunlianApiKeyCapability,
  type KunlianApiKeyIssued,
  type KunlianApiKeyItem,
  type KunlianApiKeyUpdatePayload,
  type KunlianDirectoryTenantItem,
} from "@/types/api/kunlianApiKey";
import { TenantScopeSelector } from "./TenantScopeSelector";
import {
  isAllTenantsScope,
  mergeUniqueTenants,
  normalizeUtcIso,
  parseBackendUtcDate,
  parseTenantIdsInput,
  sameStringSet,
  sameTimestamp,
} from "./utils";

export interface KeyFormDialogProps {
  editingKey: KunlianApiKeyItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onIssued: (issued: KunlianApiKeyIssued) => void;
  onUpdated: () => void;
}

const DEFAULT_INTEGRATION_ID = "kunlian";
const MAX_TENANT_COUNT = 1000;
const MAX_IDENTIFIER_LENGTH = 128;

export function KeyFormDialog({
  editingKey,
  open,
  onOpenChange,
  onIssued,
  onUpdated,
}: KeyFormDialogProps) {
  const { t } = useTranslation();
  const [connectionId, setConnectionId] = useState("");
  const [integrationId, setIntegrationId] = useState(DEFAULT_INTEGRATION_ID);
  const [allTenants, setAllTenants] = useState(false);
  const [tenantInput, setTenantInput] = useState("");
  const [tenantIds, setTenantIds] = useState<string[]>([]);
  const [tenantError, setTenantError] = useState<string | null>(null);
  const [availableTenants, setAvailableTenants] = useState<
    KunlianDirectoryTenantItem[]
  >([]);
  const [loadingTenants, setLoadingTenants] = useState(false);
  const [capabilities, setCapabilities] = useState<KunlianApiKeyCapability[]>(
    [],
  );
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const connectionTouchedRef = useRef(false);

  const isEdit = Boolean(editingKey);

  const fetchTenants = useCallback(async (targetConnectionId?: string) => {
    setLoadingTenants(true);
    try {
      const response = await getKunlianTenantsSilentApi(targetConnectionId);
      setAvailableTenants(response?.items || []);
    } finally {
      setLoadingTenants(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    connectionTouchedRef.current = false;
    setTenantInput("");
    setTenantError(null);

    if (editingKey) {
      setConnectionId(editingKey.connection_id);
      setIntegrationId(editingKey.integration_id);
      if (isAllTenantsScope(editingKey.tenant_ids)) {
        setAllTenants(true);
        setTenantIds([]);
      } else {
        setAllTenants(false);
        setTenantIds([...editingKey.tenant_ids]);
      }
      setCapabilities([...editingKey.capabilities]);
      setExpiresAt(normalizeUtcIso(editingKey.expires_at));
      void fetchTenants(editingKey.connection_id);
      return;
    }

    setConnectionId("");
    setIntegrationId(DEFAULT_INTEGRATION_ID);
    setAllTenants(false);
    setTenantIds([]);
    setCapabilities(["read", "invoke"]);
    setExpiresAt(null);

    let cancelled = false;
    void getKunlianIntegrationStatusSilentApi().then((status) => {
      if (cancelled) return;
      const detected = status?.connection_id?.trim();
      if (detected && !connectionTouchedRef.current) {
        setConnectionId(detected);
        void fetchTenants(detected);
      } else {
        void fetchTenants();
      }
    });
    return () => {
      cancelled = true;
    };
  }, [open, editingKey, fetchTenants]);

  const trimmedConnectionId = connectionId.trim();
  const trimmedIntegrationId = integrationId.trim();
  const connectionTooLong = trimmedConnectionId.length > MAX_IDENTIFIER_LENGTH;
  const integrationTooLong = trimmedIntegrationId.length > MAX_IDENTIFIER_LENGTH;
  const expiresDate = parseBackendUtcDate(expiresAt);
  const expiresInvalid = Boolean(
    expiresAt && (!expiresDate || expiresDate.getTime() <= Date.now()),
  );

  const resolvePendingTenantTokens = (): string[] | null => {
    const { valid, tooLong, hasWildcard } = parseTenantIdsInput(tenantInput);
    if (hasWildcard) {
      setTenantError(t("kunlianApiKey.validation.wildcardUseModeToggle"));
      return null;
    }
    if (tooLong.length > 0) {
      setTenantError(t("kunlianApiKey.validation.tenantTooLong"));
      return null;
    }
    if (!valid.length) return tenantIds;
    const merged = mergeUniqueTenants(tenantIds, valid);
    if (merged.length > MAX_TENANT_COUNT) {
      setTenantError(
        t("kunlianApiKey.validation.tenantCountLimit", {
          max: MAX_TENANT_COUNT,
        }),
      );
      return null;
    }
    setTenantError(null);
    setTenantIds(merged);
    setTenantInput("");
    return merged;
  };

  const toggleCapability = (
    capability: KunlianApiKeyCapability,
    checked: boolean,
  ) => {
    setCapabilities((current) => {
      if (checked) {
        return current.includes(capability)
          ? current
          : [...current, capability];
      }
      return current.filter((item) => item !== capability);
    });
  };

  const allCapabilitiesSelected =
    capabilities.length === KUNLIAN_API_KEY_CAPABILITIES.length;

  const handleToggleAllCapabilities = () => {
    setCapabilities(
      allCapabilitiesSelected ? [] : [...KUNLIAN_API_KEY_CAPABILITIES],
    );
  };

  const hasValidTenantScope =
    allTenants || tenantIds.length > 0 || Boolean(tenantInput.trim());

  const canSubmit =
    !submitting &&
    Boolean(trimmedConnectionId) &&
    Boolean(trimmedIntegrationId) &&
    !connectionTooLong &&
    !integrationTooLong &&
    hasValidTenantScope &&
    capabilities.length > 0 &&
    !expiresInvalid;

  const handleSubmit = async () => {
    let finalTenants: string[];
    if (allTenants) {
      finalTenants = [KUNLIAN_ALL_TENANTS_WILDCARD];
    } else {
      const committed = tenantInput.trim()
        ? resolvePendingTenantTokens()
        : tenantIds;
      if (committed === null) return;
      finalTenants = committed;
    }

    if (
      !trimmedConnectionId ||
      !trimmedIntegrationId ||
      connectionTooLong ||
      integrationTooLong ||
      finalTenants.length === 0 ||
      capabilities.length === 0 ||
      expiresInvalid
    ) {
      return;
    }

    const serializedExpiresAt = expiresDate
      ? expiresDate.toISOString()
      : null;

    setSubmitting(true);
    try {
      if (editingKey) {
        const patch: KunlianApiKeyUpdatePayload = {};
        if (!sameStringSet(finalTenants, editingKey.tenant_ids)) {
          patch.tenant_ids = finalTenants;
        }
        if (!sameStringSet(capabilities, editingKey.capabilities)) {
          patch.capabilities = capabilities;
        }
        if (!sameTimestamp(serializedExpiresAt, editingKey.expires_at)) {
          patch.expires_at = serializedExpiresAt;
        }
        if (Object.keys(patch).length === 0) {
          onOpenChange(false);
          return;
        }
        await updateKunlianApiKeyApi(editingKey.id, patch);
        notification.open({
          type: "success",
          title: String(t("kunlianApiKey.form.editTitle") ?? ""),
          description: String(t("kunlianApiKey.feedback.updated") ?? ""),
        });
        onUpdated();
        return;
      }

      const issued = await issueKunlianApiKeyApi({
        connection_id: trimmedConnectionId,
        integration_id: trimmedIntegrationId,
        tenant_ids: finalTenants,
        capabilities,
        expires_at: serializedExpiresAt,
      });
      notification.open({
        type: "success",
        title: String(t("kunlianApiKey.form.issueTitle") ?? ""),
        description: String(t("kunlianApiKey.feedback.issued") ?? ""),
      });
      onIssued(issued);
    } catch (error) {
      showApiError(error);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!submitting) onOpenChange(nextOpen);
      }}
    >
      <DialogContent className="sm:max-w-[680px]">
        <DialogHeader>
          <DialogTitle>
            {t(
              isEdit
                ? "kunlianApiKey.form.editTitle"
                : "kunlianApiKey.form.issueTitle",
            )}
          </DialogTitle>
          <DialogDescription>
            {t("kunlianApiKey.form.description")}
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[68vh] space-y-4 overflow-y-auto py-2 pr-1">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="kl-connection-id">
                {t("kunlianApiKey.fields.connectionId")} *
              </Label>
              <Input
                id="kl-connection-id"
                value={connectionId}
                disabled={isEdit}
                maxLength={MAX_IDENTIFIER_LENGTH}
                status={connectionTooLong ? "error" : "default"}
                placeholder={t("kunlianApiKey.form.connectionIdPlaceholder")}
                onChange={(event) => {
                  connectionTouchedRef.current = true;
                  setConnectionId(event.target.value);
                }}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="kl-integration-id">
                {t("kunlianApiKey.fields.integrationId")} *
              </Label>
              <Input
                id="kl-integration-id"
                value={integrationId}
                disabled={isEdit}
                maxLength={MAX_IDENTIFIER_LENGTH}
                status={integrationTooLong ? "error" : "default"}
                placeholder={t("kunlianApiKey.form.integrationIdPlaceholder")}
                onChange={(event) => setIntegrationId(event.target.value)}
              />
            </div>
          </div>

          <TenantScopeSelector
            availableTenants={availableTenants}
            loadingTenants={loadingTenants}
            allTenants={allTenants}
            onAllTenantsChange={setAllTenants}
            selectedTenantIds={tenantIds}
            onSelectedTenantIdsChange={setTenantIds}
            tenantInput={tenantInput}
            onTenantInputChange={setTenantInput}
            tenantError={tenantError}
            onTenantErrorChange={setTenantError}
            onRefreshTenants={() =>
              void fetchTenants(trimmedConnectionId || undefined)
            }
            maxTenantCount={MAX_TENANT_COUNT}
          />

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>{t("kunlianApiKey.fields.capabilities")} *</Label>
              <Button
                type="button"
                size="small"
                variant="link"
                onClick={handleToggleAllCapabilities}
              >
                {t(
                  allCapabilitiesSelected
                    ? "kunlianApiKey.actions.clearCapabilities"
                    : "kunlianApiKey.actions.selectAllCapabilities",
                )}
              </Button>
            </div>
            <div className="space-y-2 rounded-md border p-3">
              {KUNLIAN_API_KEY_CAPABILITIES.map((capability) => {
                const checked = capabilities.includes(capability);
                return (
                  <label
                    key={capability}
                    className="flex cursor-pointer items-start gap-2"
                  >
                    <Checkbox
                      className="mt-0.5"
                      checked={checked}
                      onCheckedChange={(next) =>
                        toggleCapability(capability, next === true)
                      }
                    />
                    <span className="min-w-0 space-y-0.5">
                      <span className="block text-sm font-medium">
                        {t(`kunlianApiKey.capabilities.${capability}.label`)}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {t(`kunlianApiKey.capabilities.${capability}.desc`)}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>{t("kunlianApiKey.fields.expiresAt")}</Label>
            <div className="flex items-center gap-2">
              <DatePicker
                showTime
                value={expiresAt || undefined}
                placeholder={t("kunlianApiKey.form.expiresAtPlaceholder")}
                onChange={(date) => setExpiresAt(date.toISOString())}
              />
              {expiresAt ? (
                <Button
                  type="button"
                  variant="link"
                  className="shrink-0 px-0"
                  onClick={() => setExpiresAt(null)}
                >
                  {t("kunlianApiKey.actions.neverExpires")}
                </Button>
              ) : null}
            </div>
            {expiresInvalid ? (
              <p className="text-xs text-destructive">
                {t("kunlianApiKey.validation.expiresFuture")}
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                {t("kunlianApiKey.form.expiresAtHint")}
              </p>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button
            type="button"
            variant="outlined"
            color="default"
            disabled={submitting}
            onClick={() => onOpenChange(false)}
          >
            {t("cancel")}
          </Button>
          <Button type="button" disabled={!canSubmit} onClick={handleSubmit}>
            {submitting ? (
              <Outlined.Loading
                aria-hidden="true"
                className="mr-2 size-4 animate-spin"
              />
            ) : null}
            {t(isEdit ? "save" : "kunlianApiKey.actions.issue")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
