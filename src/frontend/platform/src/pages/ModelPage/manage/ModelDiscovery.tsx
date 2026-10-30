import { Button } from "@bisheng/ui";
import { Checkbox } from "@bisheng/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog";
import { Input } from "@bisheng/ui";
import { Select } from "@bisheng/ui";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import {
  DiscoveredModel,
  DiscoveryConnection,
  DiscoveryResult,
  DiscoverySource,
  ModelType,
  discoverModels,
} from "@/controllers/API/modelDiscovery";
import { Loader2, Plus, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  availableModelTypes,
  discoveryProviders,
  importableModels,
} from "./modelDiscoveryState";

import { ModelDiscoveryOptions } from "./ModelDiscoveryOptions";

interface ModelDiscoveryProps {
  provider: string;
  connectionVersion: number;
  autoFetchVersion: number;
  existing: string[];
  getConnection: () => DiscoveryConnection | null;
  onImport: (models: DiscoveredModel[]) => void;
}

export function ModelDiscovery({
  provider,
  connectionVersion,
  autoFetchVersion,
  existing,
  getConnection,
  onImport,
}: ModelDiscoveryProps) {
  const { t } = useTranslation("model");
  const selectLabels = useSelectLabels();
  const [source, setSource] = useState<DiscoverySource>("auto");
  const [options, setOptions] = useState<Record<string, string>>({});
  const [resultInfo, setResultInfo] = useState<DiscoveryResult | null>(null);
  const [deploymentNames, setDeploymentNames] = useState<
    Record<string, string>
  >({});
  const [open, setOpen] = useState(false);
  const [catalog, setCatalog] = useState<DiscoveredModel[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [types, setTypes] = useState<Record<string, ModelType>>({});
  const [keyword, setKeyword] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [requiredReason, setRequiredReason] = useState("");
  const triggerRef = useRef<HTMLButtonElement>(null);
  const requestVersion = useRef(0);
  const lastConnection = useRef("");
  const supported = discoveryProviders.has(provider);
  const allowedTypes = availableModelTypes(provider);
  const needsDeployment = resultInfo?.scope === "azure_models";
  const candidates = importableModels(
    catalog || [],
    selected,
    types,
    needsDeployment ? [] : existing,
    provider,
  );
  const eligible = needsDeployment
    ? candidates
        .flatMap((model) => {
          const name = deploymentNames[model.model_name]?.trim();
          return name && name.length <= 100 && !existing.includes(name)
            ? [{ ...model, model_name: name }]
            : [];
        })
        .filter(
          (model, index, models) =>
            models.findIndex((item) => item.model_name === model.model_name) ===
            index,
        )
    : candidates;
  const visible = (catalog || []).filter((model) => {
    const type = types[model.model_name] || model.model_type;
    return (
      `${model.model_name} ${model.display_name}`
        .toLowerCase()
        .includes(keyword.trim().toLowerCase()) &&
      (typeFilter === "all" ||
        (typeFilter === "unknown" ? !type : type === typeFilter))
    );
  });
  const selectable = visible.filter((model) => {
    const type = types[model.model_name] || model.model_type;
    return (
      !existing.includes(
        needsDeployment
          ? deploymentNames[model.model_name]?.trim()
          : model.model_name,
      ) &&
      (!needsDeployment || !!deploymentNames[model.model_name]?.trim()) &&
      model.type_source !== "unsupported" &&
      type &&
      allowedTypes.includes(type)
    );
  });
  const allVisibleSelected =
    selectable.length > 0 &&
    selectable.every((model) => selected.has(model.model_name));

  useEffect(() => {
    requestVersion.current += 1;
    lastConnection.current = "";
    setResultInfo(null);
    setDeploymentNames({});
    setCatalog(null);
    setSelected(new Set());
    setTypes({});
    setKeyword("");
    setTypeFilter("all");
    setError("");
    setLoading(false);
    setOpen(false);
    setRequiredReason("");
    setSource("auto");
    setOptions({});
    return () => {
      requestVersion.current += 1;
    };
  }, [provider, connectionVersion]);

  const handleFetch = async (automatic = false) => {
    if (!supported) return;
    const connection = getConnection();
    if (!connection) return;
    const identity = JSON.stringify([connection, source, options]);
    if (automatic && identity === lastConnection.current) return;
    lastConnection.current = identity;
    const version = ++requestVersion.current;
    setOpen(true);
    setLoading(true);
    setError("");
    setResultInfo(null);
    setDeploymentNames({});
    setCatalog(null);
    setSelected(new Set());
    setTypes({});
    try {
      const result = await discoverModels({ ...connection, source, options });
      if (version === requestVersion.current) {
        setCatalog(result.models);
        setResultInfo(result);
        setRequiredReason("");
      }
    } catch (failure: unknown) {
      if (version === requestVersion.current) {
        lastConnection.current = "";
        const failureData = failure as {
          data?: { reason?: string };
          response?: { data?: { data?: { reason?: string } } };
        };
        const reason =
          failureData?.data?.reason ??
          failureData?.response?.data?.data?.reason;
        setRequiredReason(
          ["workspace", "credentials", "resource", "region"].includes(
            reason || "",
          )
            ? reason!
            : "",
        );
        const reasons = new Set([
          "auth",
          "timeout",
          "unsupported",
          "address",
          "connection",
          "format",
          "limit",
          "credentials",
          "workspace",
          "resource",
          "region",
          "rate_limit",
        ]);
        setError(
          t(
            reason && reasons.has(reason)
              ? `model.discoveryError_${reason}`
              : "model.discoveryFailure",
          ),
        );
      }
    } finally {
      if (version === requestVersion.current) setLoading(false);
    }
  };
  const fetchCurrent = useRef(handleFetch);
  fetchCurrent.current = handleFetch;
  useEffect(() => {
    if (autoFetchVersion > 0) void fetchCurrent.current(true);
  }, [autoFetchVersion]);

  const handleOptionsChange = (
    nextSource: DiscoverySource,
    nextOptions: Record<string, string>,
  ) => {
    requestVersion.current += 1;
    lastConnection.current = "";
    if (nextSource !== source) setRequiredReason("");
    setSource(nextSource);
    setOptions(nextOptions);
    setCatalog(null);
    setResultInfo(null);
    setDeploymentNames({});
    setSelected(new Set());
    setTypes({});
    setError("");
    setLoading(false);
  };
  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      requestVersion.current += 1;
      setLoading(false);
      setOptions({});
      setRequiredReason("");
      lastConnection.current = "";
    }
  };

  if (!supported) return null;

  return (
    <>
      <Button
        ref={triggerRef}
        size="small"
        variant="outlined"
        color="default"
        onClick={() => {
          if (catalog) setOpen(true);
          else void handleFetch();
        }}
      >
        <Plus className="mr-1 size-4" />
        {t("model.selectModels")}
      </Button>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent
          className="flex max-h-[calc(100vh-64px)] w-[calc(100vw-32px)] flex-col sm:max-w-[720px]"
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            triggerRef.current?.focus();
          }}
        >
          <DialogHeader>
            <DialogTitle>{t("model.selectModels")}</DialogTitle>
            <DialogDescription>{t("model.modelPickerHint")}</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3 min-h-0 overflow-y-auto">
            <ModelDiscoveryOptions
              key={`${provider}:${open}`}
              requiredReason={requiredReason}
              provider={provider}
              source={source}
              options={options}
              onChange={handleOptionsChange}
            />
            {resultInfo && (
              <div role="status" className="text-xs text-muted-foreground">
                <p>
                  {t(
                    resultInfo.source === "preset"
                      ? "model.discoveryPresetNotice"
                      : `model.discoveryScope_${resultInfo.scope || "catalog"}`,
                    { date: resultInfo.catalog_date },
                  )}
                </p>
                {resultInfo.source === "preset" &&
                  resultInfo.docs_url?.startsWith("https://") && (
                    <a
                      className="text-primary"
                      href={resultInfo.docs_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {t("model.discoveryDocs")}
                    </a>
                  )}
              </div>
            )}
            <div className="flex items-center gap-2">
              <Input
                aria-label={t("model.searchDiscoveredModels")}
                value={keyword}
                placeholder={t("model.searchDiscoveredModels")}
                onChange={(event) => setKeyword(event.target.value)}
              />
              <Select
                {...selectLabels}
                aria-label={t("model.filterModelType")}
                className="w-40 shrink-0"
                value={typeFilter}
                onChange={(value) => {
                  if (value) setTypeFilter(String(value));
                }}
                options={[
                  { value: "all", label: t("model.allModelTypes") },
                  ...allowedTypes.map((type) => ({
                    value: type,
                    label: t(`model.type_${type}`),
                  })),
                  { value: "unknown", label: t("model.unknownModelType") },
                ]}
              />
            </div>
            <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
              <label className="flex items-center gap-2 cursor-pointer">
                <Checkbox
                  aria-label={t("model.selectVisibleModels")}
                  checked={allVisibleSelected}
                  disabled={selectable.length === 0 || loading}
                  onCheckedChange={() =>
                    setSelected((previous) => {
                      const next = new Set(previous);
                      selectable.forEach((model) =>
                        allVisibleSelected
                          ? next.delete(model.model_name)
                          : next.add(model.model_name),
                      );
                      return next;
                    })
                  }
                />
                {t("model.selectVisibleModels")}
              </label>
              <div className="flex items-center gap-2">
                {catalog && (
                  <span>
                    {t("model.discoveredCount", { count: catalog.length })}
                  </span>
                )}
                <Button
                  size="small"
                  variant="text"
                  color="default"
                  disabled={loading}
                  onClick={() => void handleFetch()}
                >
                  <RefreshCw
                    className={`mr-1 size-3.5 ${loading ? "animate-spin" : ""}`}
                  />
                  {t("model.refreshModels")}
                </Button>
              </div>
            </div>
            <div className="min-h-40 max-h-[50vh] overflow-y-auto overscroll-contain rounded-md border divide-y">
              {loading && (
                <div
                  role="status"
                  className="flex items-center justify-center gap-2 py-14 text-sm text-muted-foreground"
                >
                  <Loader2 className="size-4 animate-spin" />
                  {t("model.fetchingModels")}
                </div>
              )}
              {error && (
                <div role="alert" className="p-6 text-sm text-destructive">
                  {error}
                </div>
              )}
              {!loading &&
                !error &&
                visible.map((model) => {
                  const added = existing.includes(
                    needsDeployment
                      ? deploymentNames[model.model_name]?.trim()
                      : model.model_name,
                  );
                  const type = types[model.model_name] || model.model_type;
                  const unsupported =
                    model.type_source === "unsupported" ||
                    (!!type && !allowedTypes.includes(type));
                  return (
                    <div
                      key={model.model_name}
                      className="flex items-center gap-3 px-3 py-2.5"
                    >
                      <Checkbox
                        aria-label={model.model_name}
                        checked={selected.has(model.model_name)}
                        disabled={
                          added ||
                          unsupported ||
                          !type ||
                          (needsDeployment &&
                            !deploymentNames[model.model_name]?.trim())
                        }
                        onCheckedChange={(checked) =>
                          setSelected((previous) => {
                            const next = new Set(previous);
                            if (checked === true) next.add(model.model_name);
                            else next.delete(model.model_name);
                            return next;
                          })
                        }
                      />
                      <div className="flex min-w-0 flex-1 items-center gap-2">
                        <p
                          className="min-w-0 truncate text-sm"
                          title={model.model_name}
                        >
                          {model.model_name}
                        </p>
                        {(added || unsupported) && (
                          <span className="shrink-0 text-xs text-muted-foreground">
                            {t(
                              added
                                ? "model.modelAlreadyAdded"
                                : "model.discoveryUnsupportedType",
                            )}
                          </span>
                        )}
                      </div>
                      {needsDeployment && (
                        <Input
                          className="w-36"
                          aria-label={t("model.discoveryDeploymentFor", {
                            name: model.model_name,
                          })}
                          placeholder={t("model.discoveryDeploymentName")}
                          value={deploymentNames[model.model_name] || ""}
                          maxLength={100}
                          onChange={(event) =>
                            setDeploymentNames((previous) => ({
                              ...previous,
                              [model.model_name]: event.target.value,
                            }))
                          }
                        />
                      )}
                      {((model.type_source === "unknown" ||
                        model.type_source === "speech") &&
                        !added &&
                        !unsupported) ? (
                        <Select
                          {...selectLabels}
                          aria-label={t("model.confirmModelTypeFor", {
                            name: model.model_name,
                          })}
                          className="w-36"
                          placeholder={t("model.confirmModelType")}
                          value={type || null}
                          onChange={(value) => {
                            if (value)
                              setTypes((previous) => ({
                                ...previous,
                                [model.model_name]: value as ModelType,
                              }));
                          }}
                          options={(model.type_source === "speech"
                            ? (["asr", "asr_rt"] as const)
                            : allowedTypes
                          ).map((value) => ({
                            value,
                            label: t(`model.type_${value}`),
                          }))}
                        />
                      ) : (
                        <span className="shrink-0 rounded bg-muted px-2 py-1 text-xs text-muted-foreground">
                          {t(
                            type
                              ? `model.type_${type}`
                              : "model.unknownModelType",
                          )}
                        </span>
                      )}
                    </div>
                  );
                })}
              {!loading && !error && catalog && visible.length === 0 && (
                <p className="px-4 py-14 text-center text-sm text-muted-foreground">
                  {t(
                    catalog.length
                      ? "model.noMatchingModels"
                      : "model.emptyModelCatalog",
                  )}
                </p>
              )}
            </div>
          </div>
          <DialogFooter className="items-center gap-2 sm:justify-between">
            <span className="text-sm text-muted-foreground">
              {t("model.selectedModelCount", { count: eligible.length })}
            </span>
            <div className="flex gap-2">
              <Button
                variant="outlined"
                color="default"
                onClick={() => handleOpenChange(false)}
              >
                {t("model.cancel")}
              </Button>
              <Button
                disabled={eligible.length === 0 || loading}
                onClick={() => {
                  onImport(eligible);
                  setSelected(new Set());
                  handleOpenChange(false);
                }}
              >
                {t("model.addSelectedModels", { count: eligible.length })}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
