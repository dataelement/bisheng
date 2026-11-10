import { Outlined } from "bisheng-icons";
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
import { getAuditUsers } from "@/controllers/API/dshModelAudit";
import type { AuditUserOption } from "@/types/dshModelAudit";
import { Check } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

interface ModelAuditUserSelectProps {
  tenantId?: number;
  value?: number;
  onChange: (userId: number | undefined) => void;
}

export function ModelAuditUserSelect({
  tenantId,
  value,
  onChange,
}: ModelAuditUserSelectProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [users, setUsers] = useState<AuditUserOption[]>([]);
  const [selected, setSelected] = useState<AuditUserOption>();
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
        getAuditUsers(
          {
            tenant_id: tenantId,
            keyword: keyword.trim() || undefined,
            page,
            page_size: 20,
          },
          abort.signal,
        )
          .then((result) => {
            if (abort.signal.aborted) return;
            const valid = result.data.filter(
              (user) => Number.isSafeInteger(user.user_id) && user.user_id > 0,
            );
            setUsers((old) => [
              ...new Map(
                (page === 1 ? valid : [...old, ...valid]).map((user) => [
                  user.user_id,
                  user,
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
  }, [open, keyword, page, tenantId, revision]);

  const handleLoadMore = () => {
    if (!loading && !failed && hasMore) {
      setLoading(true);
      setPage((old) => old + 1);
    }
  };

  return (
    <div className="min-w-0 space-y-1">
      <span className="block text-xs text-muted-foreground">
        {t("dsh.modelAuditView.filterUser")}
      </span>
      <Popover
        open={open}
        modal={false}
        onOpenChange={(next) => {
          setOpen(next);
          setKeyword("");
          setPage(1);
          setUsers([]);
          setFailed(false);
          setHasMore(false);
          setLoading(next);
        }}
      >
        <PopoverTrigger asChild>
          <button
            type="button"
            className="input-touch-hit relative flex h-8 w-full min-w-0 cursor-pointer items-center gap-2 overflow-hidden rounded-md border border-border-base bg-bg-page px-[11px] text-left text-[length:var(--font-size-3)] font-normal leading-[var(--line-height-3)] text-text-1 outline-none transition-colors hover:border-border-deep focus-visible:border-border-deep focus-visible:shadow-focus data-[state=open]:border-border-deep data-[state=open]:shadow-focus"
            aria-label={t("dsh.modelAuditView.selectUser")}
            aria-expanded={open}
          >
            <span className="truncate">
              {value === undefined
                ? t("dsh.modelAuditView.allUsers")
                : selected?.user_id === value
                  ? selected.user_name
                  : t("dsh.modelAuditView.selectedUser", { id: value })}
            </span>
            <Outlined.Down
              className={`ml-auto size-4 shrink-0 text-text-3 transition-transform${open ? " rotate-180" : ""}`}
              aria-hidden="true"
            />
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          className="w-80 max-w-[calc(100vw-2rem)] p-0"
        >
          <Command shouldFilter={false} label={t("dsh.userSearchResults")}>
            <CommandInput
              value={keyword}
              maxLength={128}
              placeholder={t("dsh.searchUsers")}
              aria-label={t("dsh.searchUsers")}
              onValueChange={(next) => {
                setKeyword(next);
                setPage(1);
                setUsers([]);
                setHasMore(false);
                setFailed(false);
                setLoading(true);
              }}
            />
            <CommandList
              aria-label={t("dsh.userSearchResults")}
              aria-busy={loading}
              className="h-60 max-h-60 overflow-y-auto"
              onScroll={(event) => {
                const { scrollHeight, scrollTop, clientHeight } =
                  event.currentTarget;
                if (scrollHeight - scrollTop - clientHeight < 24)
                  handleLoadMore();
              }}
            >
              <CommandItem
                value="all-users"
                onSelect={() => {
                  onChange(undefined);
                  setOpen(false);
                }}
              >
                {t("dsh.modelAuditView.allUsers")}
                {value === undefined && (
                  <Check className="ml-auto size-4" aria-hidden="true" />
                )}
              </CommandItem>
              {users.map((user) => (
                <CommandItem
                  key={user.user_id}
                  value={String(user.user_id)}
                  onSelect={() => {
                    setSelected(user);
                    onChange(user.user_id);
                    setOpen(false);
                  }}
                >
                  <span className="truncate">{user.user_name}</span>
                  {value === user.user_id && (
                    <Check className="ml-auto size-4" aria-hidden="true" />
                  )}
                </CommandItem>
              ))}
              {loading && (
                <p role="status" className="p-4 text-sm text-muted-foreground">
                  {t("dsh.loading")}
                </p>
              )}
              {failed && (
                <>
                  <p role="alert" className="p-4 text-sm text-muted-foreground">
                    {t("dsh.modelAuditView.userLoadError")}
                  </p>
                  <CommandItem
                    value="retry"
                    onSelect={() => setRevision((old) => old + 1)}
                  >
                    {t("dsh.refresh")}
                  </CommandItem>
                </>
              )}
              {!loading && !failed && users.length === 0 && (
                <p role="status" className="p-4 text-sm text-muted-foreground">
                  {t("dsh.modelAuditView.noUsers")}
                </p>
              )}
              {hasMore && !loading && !failed && (
                <CommandItem value="next-page" onSelect={handleLoadMore}>
                  {t("dsh.loadMoreUsers")}
                </CommandItem>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
}
