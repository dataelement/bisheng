import { Checkbox } from "@bisheng/ui";
import { Search, User as UserIcon } from "lucide-react";
import { getGrantSubjectUsersApi, type GrantSubjectUser } from "@/controllers/API/permission";
import { useTranslation } from "react-i18next";
import { useSubjectSearch } from "../selectComponent/useSubjectSearch";
import { SubjectBusinessId, SubjectSearchStatus } from "../selectComponent/SubjectSearchStatus";
import { ResourceType, SelectedSubject } from "./types";

interface SubjectSearchUserProps {
  value: SelectedSubject[];
  onChange: (value: SelectedSubject[]) => void;
  resourceType?: ResourceType;
  resourceId?: string;
  disabledIds?: number[];
  scopeKey?: string;
  fetchPage?: (
    keyword: string,
    page: number,
    signal: AbortSignal,
  ) => Promise<{ data: GrantSubjectUser[]; total: number }>;
  searchPlaceholder?: string;
}

export function SubjectSearchUser({
  value,
  onChange,
  resourceType,
  resourceId,
  disabledIds = [],
  scopeKey,
  fetchPage,
  searchPlaceholder,
}: SubjectSearchUserProps) {
  const { t } = useTranslation("permission");
  const search = useSubjectSearch<GrantSubjectUser>({
    retainRowsOnAppend: true,
    scopeKey: scopeKey ?? `${resourceType}:${resourceId}`,
    fetchPage:
      fetchPage ??
      (async (keyword, page, signal) => {
        if (!resourceType || !resourceId) return { data: [], total: 0 };
        return getGrantSubjectUsersApi(resourceType, resourceId, { keyword, page, pageSize: 50 }, { signal });
      }),
  });
  const selectedIds = new Set(
    value.filter((subject) => subject.type === "user").map((subject) => subject.id),
  );
  const disabled = new Set(disabledIds);
  const toggle = (user: GrantSubjectUser) => {
    if (search.loading || search.failed || search.tooLong || disabled.has(user.user_id)) return;
    onChange(
      selectedIds.has(user.user_id)
        ? value.filter((subject) => subject.type !== "user" || subject.id !== user.user_id)
        : [
            ...value,
            {
              type: "user",
              id: user.user_id,
              name: user.user_name,
              externalId: user.external_id ?? null,
              departmentPath: user.department_path ?? user.primary_department_path ?? undefined,
            },
          ],
    );
  };
  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="relative shrink-0">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[#999999]" />
        <input
          type="text"
          placeholder={searchPlaceholder ?? t("search.user")}
          {...search.inputProps}
          className="h-8 w-full rounded-[6px] border border-[#EBECF0] bg-white pl-9 pr-3 text-[14px] text-[#212121] outline-none transition-colors placeholder:text-[#999999] focus:border-[#C9CDD4]"
        />
      </div>
      <div
        className="min-h-0 flex-1 overflow-y-auto rounded-[6px] border border-[#EBECF0]"
        onScroll={(event) => {
          const element = event.currentTarget;
          if (element.scrollTop + element.clientHeight >= element.scrollHeight - 100) search.loadMore();
        }}
      >
        <SubjectSearchStatus
          permission
          tooLong={search.tooLong}
          failed={search.failed}
          loading={search.loading}
          empty={search.rows.length === 0}
          onRetry={search.retry}
        />
        {!search.loading &&
          !search.failed &&
          !search.tooLong &&
          search.rows.map((user) => (
            <div
              key={user.user_id}
              className={`flex min-w-0 items-center gap-2 px-3 py-2 ${disabled.has(user.user_id) ? "cursor-not-allowed opacity-60" : "cursor-pointer hover:bg-accent"}`}
              onClick={() => toggle(user)}
            >
              <Checkbox
                className="peer"
                checked={selectedIds.has(user.user_id) || disabled.has(user.user_id)}
                disabled={disabled.has(user.user_id)}
              />
              <UserIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm" title={user.user_name}>
                  {user.user_name}
                </div>
                <SubjectBusinessId kind="user" value={user.external_id} />
                <div
                  className="truncate text-xs text-muted-foreground"
                  title={user.department_path ?? user.primary_department_path ?? undefined}
                >
                  {user.department_path || user.primary_department_path}
                </div>
              </div>
            </div>
          ))}
        <SubjectSearchStatus
          loading={search.loadingMore}
          failed={search.loadMoreFailed}
          onRetry={search.retry}
        />
        {!search.loading &&
          !search.loadingMore &&
          !search.failed &&
          !search.loadMoreFailed &&
          search.rows.length < search.total && (
            <button type="button" onClick={search.loadMore}>
              {t("subjectSearch.loadMore", { ns: "bs" })}
            </button>
          )}
      </div>
    </div>
  );
}
