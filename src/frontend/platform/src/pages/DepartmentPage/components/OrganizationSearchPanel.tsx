import { useState, type ReactNode } from "react";
import { Button, SearchInput, Tag } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useTranslation } from "react-i18next";
import { useSubjectSearch } from "@/components/bs-comp/selectComponent/useSubjectSearch";
import { SubjectSearchStatus } from "@/components/bs-comp/selectComponent/SubjectSearchStatus";
import {
  searchOrganizationApi,
  type OrganizationDepartmentResult,
  type OrganizationMemberResult,
} from "@/controllers/API/organization";
import { showApiError } from "@/controllers/request";

interface OrganizationSearchPanelProps {
  includeArchived: boolean;
  preferredDepartmentId?: number;
  onSelectDepartment: (result: OrganizationDepartmentResult) => Promise<void>;
  onSelectMember: (result: OrganizationMemberResult) => Promise<void>;
  children: ReactNode;
}

function MatchedName({ name, keyword }: { name: string; keyword: string }) {
  const index = name.toLocaleLowerCase().indexOf(keyword.toLocaleLowerCase());
  if (index < 0) return <>{name}</>;
  return (
    <>
      {name.slice(0, index)}
      <span className="font-medium text-primary">
        {name.slice(index, index + keyword.length)}
      </span>
      {name.slice(index + keyword.length)}
    </>
  );
}

export function OrganizationSearchPanel({
  includeArchived,
  preferredDepartmentId,
  onSelectDepartment,
  onSelectMember,
  children,
}: OrganizationSearchPanelProps) {
  const { t } = useTranslation();
  const [locating, setLocating] = useState(false);
  const scopeKey = `${includeArchived}:${preferredDepartmentId ?? ""}`;
  const members = useSubjectSearch<OrganizationMemberResult>({
    emptyByDefault: true,
    retainRowsOnAppend: true,
    scopeKey,
    fetchPage: (keyword, page, signal) =>
      searchOrganizationApi<OrganizationMemberResult>(
        {
          keyword,
          page,
          kind: "members",
          include_archived: includeArchived,
          preferred_department_id: preferredDepartmentId,
        },
        signal
      ),
  });
  const departments = useSubjectSearch<OrganizationDepartmentResult>({
    emptyByDefault: true,
    retainRowsOnAppend: true,
    scopeKey,
    fetchPage: (keyword, page, signal) =>
      searchOrganizationApi<OrganizationDepartmentResult>(
        {
          keyword,
          page,
          kind: "departments",
          include_archived: includeArchived,
        },
        signal
      ),
  });
  const clear = () => {
    members.changeKeyword("");
    departments.changeKeyword("");
  };
  const handleSelect = async (select: () => Promise<void>) => {
    setLocating(true);
    try {
      await select();
      clear();
    } catch (error) {
      showApiError(error);
    } finally {
      setLocating(false);
    }
  };
  const keyword = members.normalized;
  const duplicateNames = new Set(
    members.rows
      .filter((row) =>
        members.rows.some(
          (other) =>
            other.user_id !== row.user_id &&
            other.user_name === row.user_name &&
            other.department.id === row.department.id
        )
      )
      .map((row) => row.user_name)
  );

  const renderStatus = (search: typeof members | typeof departments) => (
    <>
      {search.loading && (
        <p
          role="status"
          className="flex items-center gap-2 px-2 py-4 text-sm text-muted-foreground"
        >
          <Outlined.Loading className="size-4 animate-spin" />
          {t("loading")}
        </p>
      )}
      <SubjectSearchStatus
        tooLong={search.tooLong}
        failed={search.failed}
        onRetry={search.retry}
      />
      {!search.loading &&
        !search.failed &&
        !search.tooLong &&
        search.rows.length === 0 && (
          <p className="px-2 py-3 text-sm text-muted-foreground">
            {t("bs:organization.noResults")}
          </p>
        )}
      {search.loadMoreFailed ? (
        <Button size="small" variant="text" onClick={search.retry}>
          {t("bs:organization.retry")}
        </Button>
      ) : search.rows.length < search.total ? (
        <Button
          size="small"
          variant="text"
          disabled={search.loadingMore}
          onClick={search.loadMore}
          className="my-1 w-full"
        >
          {t(search.loadingMore ? "loading" : "bs:organization.loadMore")}
        </Button>
      ) : null}
    </>
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <SearchInput
        {...members.inputProps}
        placeholder={t("bs:organization.searchPlaceholder")}
        aria-label={t("bs:organization.searchPlaceholder")}
        clearLabel={t("bs:organization.clearSearch")}
        disabled={locating}
        className="mb-3 w-full"
        onChange={(event) => {
          members.inputProps.onChange(event);
          departments.inputProps.onChange(event);
        }}
        onCompositionStart={() => {
          members.inputProps.onCompositionStart();
          departments.inputProps.onCompositionStart();
        }}
        onCompositionEnd={(event) => {
          members.inputProps.onCompositionEnd(event);
          departments.inputProps.onCompositionEnd(event);
        }}
        onPaste={(event) => {
          members.inputProps.onPaste(event);
          departments.inputProps.onPaste(event);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") clear();
        }}
      />
      <div
        hidden={!!keyword}
        className={keyword ? "hidden" : "flex min-h-0 flex-1 flex-col"}
      >
        {children}
      </div>
      {keyword && (
        <div className="min-h-0 flex-1 overflow-y-auto" aria-busy={locating}>
          <section
            aria-label={t("bs:organization.members")}
            className="border-b pb-3"
          >
            <p className="px-2 py-1.5 text-xs text-muted-foreground">
              {t("bs:organization.members")}
            </p>
            {members.rows.map((row) => (
              <button
                key={row.user_id}
                type="button"
                disabled={locating}
                onClick={() => void handleSelect(() => onSelectMember(row))}
                className="flex w-full items-start justify-between gap-3 rounded-md px-2 py-2 text-left text-sm hover:bg-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-wait"
              >
                <span className="min-w-0 break-words">
                  <MatchedName name={row.user_name} keyword={keyword} />
                  {duplicateNames.has(row.user_name) && (
                    <span className="ml-1 text-xs text-muted-foreground">
                      ({row.person_id || row.user_id})
                    </span>
                  )}
                  {!row.enabled && (
                    <Tag size="small" className="ml-1" color="default">
                      {t("bs:department.disabled")}
                    </Tag>
                  )}
                </span>
                <span
                  className="max-w-[60%] shrink-0 break-words text-right text-xs leading-5 text-muted-foreground"
                  title={row.department.path}
                >
                  {row.department.name}
                  {!row.is_primary && t("bs:organization.secondarySuffix")}
                  {row.department.status === "archived" &&
                    t("bs:department.archivedTag")}
                </span>
              </button>
            ))}
            {renderStatus(members)}
          </section>
          <section
            aria-label={t("bs:organization.departments")}
            className="pt-3"
          >
            <p className="px-2 py-1.5 text-xs text-muted-foreground">
              {t("bs:organization.departments")}
            </p>
            {departments.rows.map((row) => (
              <button
                key={row.id}
                type="button"
                disabled={locating}
                onClick={() => void handleSelect(() => onSelectDepartment(row))}
                className="flex w-full flex-wrap items-baseline justify-between gap-x-3 gap-y-1 rounded-md px-2 py-2 text-left text-sm hover:bg-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-wait"
              >
                <span className="break-words">
                  <MatchedName name={row.name} keyword={keyword} />
                  {row.status === "archived" && t("bs:department.archivedTag")}
                </span>
                {row.parent_path && (
                  <span
                    className="break-words text-xs leading-5 text-muted-foreground"
                    title={row.parent_path}
                  >
                    {row.parent_path}
                  </span>
                )}
              </button>
            ))}
            {renderStatus(departments)}
          </section>
        </div>
      )}
    </div>
  );
}
