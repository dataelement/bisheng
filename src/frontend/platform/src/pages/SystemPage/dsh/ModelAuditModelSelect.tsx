import { Button } from "@/components/bs-ui/button";
import { Input } from "@/components/bs-ui/input";
import {
  Command,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/bs-ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/bs-ui/popover";
import { getAuditModels } from "@/controllers/API/dshModelAudit";
import type { AuditModelOption } from "@/types/dshModelAudit";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

interface ModelAuditModelSelectProps {
  tenantId?: number;
  modelId?: number;
  value?: string;
  onChange: (filter: { model_id?: number; model_name?: string }) => void;
}

export function ModelAuditModelSelect({
  tenantId,
  modelId,
  value,
  onChange,
}: ModelAuditModelSelectProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [models, setModels] = useState<AuditModelOption[]>([]);
  const [selectedName, setSelectedName] = useState("");
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!open) return;
    const abort = new AbortController();
    setLoading(true);
    setFailed(false);
    const timer = window.setTimeout(
      () => {
        getAuditModels(
          {
            tenant_id: tenantId,
            page,
            page_size: 20,
            keyword: keyword.trim() || undefined,
          },
          abort.signal,
        )
          .then((result) => {
            if (abort.signal.aborted) return;
            const valid = result.data.filter(
              (model) =>
                Number.isSafeInteger(model?.id) &&
                model.id > 0 &&
                typeof model.name === "string" &&
                model.name.trim() !== "",
            );
            setModels((old) => [
              ...new Map(
                (page === 1 ? valid : [...old, ...valid]).map((model) => [
                  model.id,
                  model,
                ]),
              ).values(),
            ]);
            setHasMore(result.data.length > 0 && page * 20 < result.total);
          })
          .catch(() => {
            if (!abort.signal.aborted) setFailed(true);
          })
          .finally(() => {
            if (!abort.signal.aborted) setLoading(false);
          });
      },
      keyword.trim() ? 250 : 0,
    );
    return () => {
      window.clearTimeout(timer);
      abort.abort();
    };
  }, [open, tenantId, keyword, page, revision]);

  return (
    <div className="space-y-1">
      <label htmlFor="audit-model_name" className="block text-sm">
        {t("dsh.modelAuditView.filters.model_name")}
      </label>
      <div className="flex items-center gap-2">
        <Input
          id="audit-model_name"
          aria-label={t("dsh.modelAuditView.filters.model_name")}
          aria-describedby="audit-model-hint"
          value={modelId === undefined ? value || "" : selectedName}
          maxLength={2048}
          onChange={(event) =>
            onChange({
              model_id: undefined,
              model_name: event.target.value || undefined,
            })
          }
        />
        <Popover
          open={open}
          modal={false}
          onOpenChange={(next) => {
            setOpen(next);
            setKeyword("");
            setPage(1);
            setModels([]);
            setHasMore(false);
            setLoading(next);
            setFailed(false);
          }}
        >
          <PopoverTrigger asChild>
            <Button variant="outline" aria-expanded={open}>
              {t("dsh.modelAuditView.selectModel")}
            </Button>
          </PopoverTrigger>
          <PopoverContent
            align="start"
            className="w-80 max-w-[calc(100vw-2rem)] p-0"
          >
            <Command
              shouldFilter={false}
              label={t("dsh.modelAuditView.selectModel")}
            >
              <CommandInput
                value={keyword}
                maxLength={128}
                placeholder={t("dsh.modelAuditView.searchModels")}
                aria-label={t("dsh.modelAuditView.searchModels")}
                onValueChange={(next) => {
                  setKeyword(next);
                  setPage(1);
                  setModels([]);
                  setHasMore(false);
                  setLoading(true);
                  setFailed(false);
                }}
              />
              <CommandList
                className="h-60 max-h-60 overflow-y-auto"
                aria-busy={loading}
              >
                <CommandItem
                  value="all-models"
                  onSelect={() => {
                    onChange({ model_id: undefined, model_name: undefined });
                    setOpen(false);
                  }}
                >
                  {t("dsh.modelAuditView.allModels")}
                </CommandItem>
                {models.map((model) => (
                  <CommandItem
                    key={model.id}
                    value={"model:" + model.id}
                    onSelect={() => {
                      setSelectedName(model.name);
                      onChange({ model_id: model.id, model_name: undefined });
                      setOpen(false);
                    }}
                  >
                    <span className="break-all">{model.name}</span>
                  </CommandItem>
                ))}
                {loading && (
                  <p
                    role="status"
                    className="p-4 text-sm text-muted-foreground"
                  >
                    {t("dsh.loading")}
                  </p>
                )}
                {failed && (
                  <>
                    <p
                      role="alert"
                      className="p-4 text-sm text-muted-foreground"
                    >
                      {t("dsh.modelAuditView.modelLoadError")}
                    </p>
                    <CommandItem
                      value="retry"
                      onSelect={() => setRevision((old) => old + 1)}
                    >
                      {t("dsh.refresh")}
                    </CommandItem>
                  </>
                )}
                {!loading && !failed && models.length === 0 && (
                  <p
                    role="status"
                    className="p-4 text-sm text-muted-foreground"
                  >
                    {t("dsh.modelAuditView.noModels")}
                  </p>
                )}
                {hasMore && !loading && !failed && (
                  <CommandItem
                    value="next-page"
                    onSelect={() => {
                      setLoading(true);
                      setPage((old) => old + 1);
                    }}
                  >
                    {t("dsh.modelAuditView.loadMoreModels")}
                  </CommandItem>
                )}
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
      </div>
      <p id="audit-model-hint" className="text-sm text-muted-foreground">
        {t("dsh.modelAuditView.modelHint")}
      </p>
    </div>
  );
}
