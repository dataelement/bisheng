import { SubjectIdentity } from "./SubjectIdentity";
import { useSubjectKeyword } from "./useSubjectKeyword";
import { Checkbox } from "~/components/ui/Checkbox";
import { Button, SearchInput, Tag } from "@bisheng/ui";
import { getCreationUserGroups, getUserGroups } from "~/api/permission";
import type { ResourceType, SelectedSubject } from "~/api/permission";
import { Outlined } from "bisheng-icons";
import { useEffect, useState } from "react";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import { PermissionEmptyState } from "./PermissionEmptyState";
import {
  PERMISSION_SUBJECT_ICON_CLASS,
  PERMISSION_SUBJECT_LIST_CLASS,
  PERMISSION_SUBJECT_ROW_CLASS,
  PERMISSION_SUBJECT_ROW_DISABLED_CLASS,
  PERMISSION_SUBJECT_ROW_INTERACTIVE_CLASS,
  PERMISSION_SUBJECT_SLOT_CLASS,
  permissionSubjectIndent,
} from "./permissionDialogStyles";

interface UserGroup {
  id: number;
  group_name: string;
}

export interface SubjectSearchUserGroupProps {
  value: SelectedSubject[];
  onChange: (v: SelectedSubject[]) => void;
  resourceType?: ResourceType;
  resourceId?: string;
  mode?: "create" | "resource";
  disabledIds?: number[];
  /** subjectId -> the permission model(s) that subject already holds here. */
  grantedLabels?: Record<string, string>;
  userGroupsApi?: typeof getUserGroups;
}

export function SubjectSearchUserGroup({
  value,
  onChange,
  resourceType,
  resourceId,
  mode = "resource",
  disabledIds = [],
  grantedLabels = {},
  userGroupsApi,
}: SubjectSearchUserGroupProps) {
  const localize = useLocalize();
  const [groups, setGroups] = useState<UserGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const input = useSubjectKeyword();
  const { keyword, setKeyword, normalized, tooLong, composing } = input;
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [resolvedQuery, setResolvedQuery] = useState("");
  const [resolvedPage, setResolvedPage] = useState(0);
  const blocked = tooLong || composing;
  const busy = loading || resolvedQuery !== normalized || resolvedPage !== page || blocked;

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    if (blocked || !resourceType || !resourceId) return;
    setLoading(true);
    setFailed(false);
    const timer = window.setTimeout(() => {
      const params = { keyword: normalized, page, pageSize: 50 };
      const request = mode === "create" && !userGroupsApi && (resourceType === "channel" || resourceType === "knowledge_space")
        ? getCreationUserGroups(resourceType, { signal: controller.signal }, params)
        : (userGroupsApi ?? getUserGroups)(resourceType, resourceId, { signal: controller.signal }, params);
      request.then((result) => {
        if (cancelled) return;
        setGroups((current) => page === 1 ? result.data : [...current, ...result.data.filter((item) => !current.some((old) => old.id === item.id))]);
        setTotal(result.total);
      }).catch(() => { if (!cancelled && !controller.signal.aborted) setFailed(true); })
        .finally(() => { if (!cancelled) { setLoading(false); setResolvedQuery(normalized); setResolvedPage(page); } });
    }, normalized ? 300 : 0);
    return () => { cancelled = true; window.clearTimeout(timer); controller.abort(); };
  }, [resourceId, resourceType, userGroupsApi, normalized, page, attempt, blocked, mode]);

  const selectedIds = new Set(value.filter((s) => s.type === "user_group").map((s) => s.id));
  const disabledIdSet = new Set(disabledIds);

  const toggle = (group: UserGroup) => {
    if (busy || disabledIdSet.has(group.id)) return;
    if (selectedIds.has(group.id)) {
      onChange(value.filter((s) => s.type !== "user_group" || s.id !== group.id));
    } else {
      onChange([
        ...value,
        { type: "user_group", id: group.id, name: group.group_name, externalId: String(group.id) },
      ]);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="relative shrink-0">
        <SearchInput
          clearLabel={localize("com_ui_clear")}
          placeholder={localize("com_permission.search_user_group")}
          value={keyword}
          onChange={(e) => { setKeyword(e.target.value); setPage(1); }}
          onCompositionStart={input.onCompositionStart}
          onCompositionEnd={(event) => { input.onCompositionEnd(event); setPage(1); }}
          onPaste={(event) => { input.onPaste(event); setPage(1); }}
          aria-invalid={tooLong}
          className="w-full"
        />
      </div>
      {tooLong && <p role="alert" className="text-caption text-danger">{localize("com_permission.search_too_long")}</p>}
      <div className="scrollbar-os min-h-0 flex-1 overflow-y-auto rounded-md border border-border-base">
        {busy && !blocked && (
          <div className="py-4 text-center text-sm text-text-3">
            {localize("com_ui_loading")}
          </div>
        )}
        {!busy && failed && <div className="flex flex-col items-center gap-2 py-4 text-body-sm text-text-3"><span>{localize("com_permission.load_failed")}</span><Button size="small" color="default" variant="outlined" onClick={() => setAttempt((value) => value + 1)}>{localize("com_ui_retry")}</Button></div>}
        {!busy && !failed && groups.length === 0 && (
          <PermissionEmptyState
            message={localize(keyword ? "com_permission.empty_search" : "com_permission.empty_user_groups")}
          />
        )}
        {!busy && !failed && groups.length > 0 && (
          <div className={PERMISSION_SUBJECT_LIST_CLASS}>
            {groups.map((group) => {
              const isDisabled = disabledIdSet.has(group.id);
              const grantedLabel = grantedLabels[String(group.id)];
              return (
                <div
                  key={group.id}
                  className={cn(
                    PERMISSION_SUBJECT_ROW_CLASS,
                    "!h-auto min-h-8 py-1",
                    isDisabled
                      ? PERMISSION_SUBJECT_ROW_DISABLED_CLASS
                      : PERMISSION_SUBJECT_ROW_INTERACTIVE_CLASS,
                  )}
                  style={{ paddingLeft: permissionSubjectIndent(0) }}
                  onClick={() => toggle(group)}
                >
                  {/* No switcher slot: this list is flat, so nothing in it expands
                      and the slot would only be dead space. The checkbox leads. */}
                  <div className={PERMISSION_SUBJECT_SLOT_CLASS}>
                    <Checkbox
                      className="border-[#D9D9D9] data-[state=checked]:border-primary data-[state=indeterminate]:border-primary"
                      checked={selectedIds.has(group.id) || isDisabled}
                      disabled={isDisabled}
                    />
                  </div>
                  <div className={PERMISSION_SUBJECT_SLOT_CLASS}>
                    <Outlined.PeopleGroup className={PERMISSION_SUBJECT_ICON_CLASS} />
                  </div>
                  <span className="min-w-0 flex-1 truncate pl-1" title={group.group_name}>
                    {group.group_name}
                  </span>
                  <SubjectIdentity type="user_group" externalId={String(group.id)} />
                  {(grantedLabel || isDisabled) && (
                    <Tag size="small" className="shrink-0">
                      {grantedLabel
                        ? localize("com_permission.already_granted_as", {
                            model: grantedLabel,
                          })
                        : localize("com_permission.already_granted")}
                    </Tag>
                  )}
                </div>
              );
            })}
          </div>
        )}
        {!busy && !failed && groups.length < total && <Button size="small" color="default" variant="outlined" onClick={() => setPage((value) => value + 1)}>{localize("com_permission.load_more")}</Button>}
      </div>
    </div>
  );
}
