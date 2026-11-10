import { Button } from "@bisheng/ui";
import { Input } from "@bisheng/ui";
import {
  Popover,
  PopoverAnchor,
  PopoverContent,
} from "@/components/bs-ui/popover";
import { getAuditModels } from "@/controllers/API/dshModelAudit";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

interface ModelAuditModelSelectProps {
  tenantId?: number;
  value?: string;
  onChange: (filter: { model_name?: string; model_id?: undefined }) => void;
}
export function ModelAuditModelSelect({
  tenantId,
  value = "",
  onChange,
}: ModelAuditModelSelectProps) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [names, setNames] = useState<string[]>([]);
  const [active, setActive] = useState(-1);
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
            keyword: value || undefined,
          },
          abort.signal,
        )
          .then((result) => {
            if (abort.signal.aborted) return;
            const valid = result.data.flatMap((model) =>
              typeof model?.name === "string" && model.name.trim()
                ? [model.name]
                : [],
            );
            setNames((old) => [
              ...new Set(page === 1 ? valid : [...old, ...valid]),
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
      value ? 250 : 0,
    );
    return () => {
      window.clearTimeout(timer);
      abort.abort();
    };
  }, [open, tenantId, value, page, revision]);
  const handleChoose = (name?: string) => {
    onChange({ model_name: name, model_id: undefined });
    setOpen(false);
    setActive(-1);
    setPage(1);
    setNames([]);
  };
  const handleOpen = () => {
    if (open) return;
    setOpen(true);
    setNames([]);
    setPage(1);
    setActive(-1);
  };
  return (
    <div className="min-w-0 space-y-1">
      <label
        htmlFor="audit-model_name"
        className="block text-xs text-muted-foreground"
      >
        {t("dsh.modelAuditView.filters.model_name")}
      </label>
      <Popover open={open} modal={false} onOpenChange={setOpen}>
        <PopoverAnchor asChild>
          <div>
            <Input
              ref={input}
              id="audit-model_name"
              role="combobox"
              autoComplete="off"
              aria-label={t("dsh.modelAuditView.filters.model_name")}
              aria-autocomplete="list"
              aria-expanded={open}
              aria-controls={open ? listId : undefined}
              aria-activedescendant={
                open && active >= 0 ? listId + "-" + active : undefined
              }
              aria-describedby="audit-model-hint"
              value={value}
              maxLength={2048}
              placeholder={t("dsh.modelAuditView.model_placeholder")}
              className="[@media(pointer:coarse)]:min-h-11 [@media(pointer:coarse)]:text-base"
              onFocus={handleOpen}
              onClick={handleOpen}
              onChange={(event) => {
                onChange({
                  model_name: event.target.value || undefined,
                  model_id: undefined,
                });
                setPage(1);
                setNames([]);
                setHasMore(false);
                setActive(-1);
                setLoading(true);
                setOpen(true);
              }}
              onKeyDown={(event) => {
                if (event.nativeEvent.isComposing) {
                  if (event.key === "Enter") event.preventDefault();
                  return;
                }
                if (event.key === "Escape" && open) {
                  event.preventDefault();
                  event.stopPropagation();
                  setOpen(false);
                }
                if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                  event.preventDefault();
                  handleOpen();
                  setActive((old) =>
                    names.length
                      ? (old +
                          (event.key === "ArrowDown" ? 1 : -1) +
                          names.length) %
                        names.length
                      : -1,
                  );
                }
                if (
                  event.key === "Enter" &&
                  open &&
                  active >= 0 &&
                  names[active]
                ) {
                  event.preventDefault();
                  handleChoose(names[active]);
                }
              }}
            />
          </div>
        </PopoverAnchor>
        <PopoverContent
          align="start"
          className="w-[var(--radix-popover-trigger-width)] min-w-64 max-w-[calc(100vw-2rem)] rounded-xl p-1 shadow-popup"
          onOpenAutoFocus={(event) => event.preventDefault()}
          onCloseAutoFocus={(event) => event.preventDefault()}
          onInteractOutside={(event) => {
            if (event.target === input.current) event.preventDefault();
          }}
        >
          <div
            id={listId}
            role="listbox"
            aria-label={t("dsh.modelAuditView.selectModel")}
            aria-busy={loading}
            className="max-h-60 overflow-y-auto"
          >
            {names.map((name, index) => (
              <div
                key={name}
                id={listId + "-" + index}
                role="option"
                aria-selected={active === index}
                className={active === index ? "rounded-md bg-primary/10" : ""}
              >
                <Button
                  type="button"
                  variant="text" color="default"
                  tabIndex={-1}
                  className="h-auto min-h-8 w-full justify-start whitespace-normal break-all text-left text-sm [@media(pointer:coarse)]:min-h-11"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => handleChoose(name)}
                >
                  {name}
                </Button>
              </div>
            ))}
            {loading && (
              <p role="status" className="p-3 text-sm text-muted-foreground">
                {t("dsh.loading")}
              </p>
            )}
            {failed && (
              <p role="alert" className="p-3 text-sm text-muted-foreground">
                {t("dsh.modelAuditView.modelLoadError")}
              </p>
            )}
            {!loading && !failed && !names.length && (
              <p role="status" className="p-3 text-sm text-muted-foreground">
                {t("dsh.modelAuditView.noModels")}
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2 border-t pt-1">
            <Button
              type="button"
              size="small"
              variant="text" color="default"
              onClick={() => handleChoose()}
            >
              {t("dsh.modelAuditView.allModels")}
            </Button>
            {failed && (
              <Button
                type="button"
                size="small"
                variant="text" color="default"
                onClick={() => setRevision((old) => old + 1)}
              >
                {t("dsh.refresh")}
              </Button>
            )}
            {hasMore && !loading && !failed && (
              <Button
                type="button"
                size="small"
                variant="text" color="default"
                onClick={() => {
                  setLoading(true);
                  setPage((old) => old + 1);
                }}
              >
                {t("dsh.modelAuditView.loadMoreModels")}
              </Button>
            )}
          </div>
        </PopoverContent>
      </Popover>
      <p id="audit-model-hint" className="text-xs text-muted-foreground">
        {t("dsh.modelAuditView.modelHint")}
      </p>
    </div>
  );
}
