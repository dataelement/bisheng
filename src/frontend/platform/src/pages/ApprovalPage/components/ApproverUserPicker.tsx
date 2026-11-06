import { Button, Input } from '@bisheng/ui';
import { SubjectBusinessId, SubjectSearchStatus } from "@/components/bs-comp/selectComponent/SubjectSearchStatus";
import { useSubjectSearch } from "@/components/bs-comp/selectComponent/useSubjectSearch";


import { getUsersApi } from "@/controllers/API/user";
import type { User } from "@/types/api/user";
import { Checkbox } from "@bisheng/ui";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

interface ApproverUserPickerProps {
  value: number[];
  names: string[];
  onChange: (ids: number[], names: string[]) => void;
}

export function ApproverUserPicker({ value, names, onChange }: ApproverUserPickerProps) {
  const { t } = useTranslation("bs");
  const selectedUsers = useRef(new Map<number, User>());
  const search = useSubjectSearch<User>({
    fetchPage: (keyword, page, signal) => getUsersApi({ name: keyword, page, pageSize: 50, simple: true }, { signal }),
  });
  useEffect(() => {
    for (const user of search.rows) selectedUsers.current.set(user.user_id, user);
  }, [search.rows]);
  return (
    <div className="space-y-3 py-2">
      <Input {...search.inputProps} placeholder={t("subjectSearch.userPlaceholder")} className={"block w-full"} />
      <div
        className="max-h-60 overflow-y-auto rounded-lg border border-border divide-y divide-border"
        onScroll={(event) => {
          const element = event.currentTarget;
          if (element.scrollTop + element.clientHeight >= element.scrollHeight - 40) search.loadMore();
        }}
      >
        <SubjectSearchStatus
          tooLong={search.tooLong}
          failed={search.failed}
          loading={search.loading}
          empty={!search.rows.length}
          onRetry={search.retry}
        />
        {!search.loading &&
          !search.failed &&
          !search.tooLong &&
          search.rows.map((user) => (
            <label
              key={user.user_id}
              className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-50/10"
            >
              <Checkbox
                checked={value.includes(user.user_id)}
                onCheckedChange={() => {
                  if (value.includes(user.user_id))
                    onChange(
                      value.filter((id) => id !== user.user_id),
                      names.filter((_, index) => value[index] !== user.user_id),
                    );
                  else onChange([...value, user.user_id], [...names, user.user_name]);
                }}
              />
              <span className="text-sm text-foreground">{user.user_name}</span>
              <SubjectBusinessId value={user.external_id} />
            </label>
          ))}
      </div>
      {!search.loading && !search.failed && !search.tooLong && search.rows.length < search.total && (
        <Button size="small" variant="text" type="button" onClick={search.loadMore} color="default">
          {t("subjectSearch.loadMore")}
        </Button>
      )}
      {value.length > 0 && (
        <div className="text-xs text-muted-foreground">
          {t("subjectSearch.selectedCount", { count: value.length })}:{" "}
          {value.map((id, index) => (
            <span key={id}>
              {names[index]} <SubjectBusinessId value={selectedUsers.current.get(id)?.external_id} />{" "}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
