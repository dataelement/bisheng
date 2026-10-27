import { Checkbox } from '@bisheng/ui';
import { Button, SearchInput, Tag } from "@bisheng/ui";
import { SubjectIdentity } from "./SubjectIdentity";
import { useSubjectKeyword } from "./useSubjectKeyword";
import { searchUsers } from "~/api/permission";
import type { GrantUser, ResourceType, SelectedSubject } from "~/api/permission";
import { Outlined } from "bisheng-icons";
import { useCallback, useEffect, useRef, useState } from "react";
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

export interface SubjectSearchUserProps {
  value: SelectedSubject[];
  onChange: (v: SelectedSubject[]) => void;
  resourceType?: ResourceType;
  resourceId?: string;
  disabledIds?: number[];
  /** subjectId -> the permission model(s) that subject already holds here. */
  grantedLabels?: Record<string, string>;
  usersApi?: typeof searchUsers;
}

type UserRow = GrantUser;

const PAGE_SIZE = 50;

export function SubjectSearchUser({
  value,
  onChange,
  resourceType,
  resourceId,
  disabledIds = [],
  grantedLabels = {},
  usersApi,
}: SubjectSearchUserProps) {
  const localize = useLocalize();
  const input = useSubjectKeyword();
  const { keyword, setKeyword, normalized, composing, tooLong } = input;
  const [results, setResults] = useState<UserRow[]>([]);
  const scope = `${resourceType}:${resourceId}`;
  const [pagingScope, setPagingScope] = useState(scope);
  const [requestedPage, setPage] = useState(1);
  // A changed resource must request page one even before the reset effect runs.
  const page = pagingScope === scope ? requestedPage : 1;
  const usersApiRef = useRef(usersApi);
  usersApiRef.current = usersApi;
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [resolved, setResolved] = useState({ query: "", page: 0, scope: "" });
  const blocked = composing || tooLong;
  const busy = blocked || loading || resolved.query !== normalized || resolved.page !== page || resolved.scope !== scope;
  const hasMore = results.length < total;
  const scrollRef = useRef<HTMLDivElement>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);
  const nextRequestedRef = useRef(false);

  useEffect(() => {
    setPagingScope(scope);
    setPage(1);
    setResults([]);
    setTotal(0);
    nextRequestedRef.current = false;
  }, [scope]);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    if (blocked || !resourceType || !resourceId) return;
    setLoading(true);
    setFailed(false);
    const timer = window.setTimeout(() => {
      (usersApiRef.current ?? searchUsers)(resourceType, resourceId, normalized,
        { page, pageSize: PAGE_SIZE }, { signal: controller.signal })
        .then((result) => {
          if (cancelled) return;
          setResults((current) => page === 1 ? result.data : [
            ...current, ...result.data.filter((row) => !current.some((old) => old.user_id === row.user_id)),
          ]);
          setTotal(result.total);
        })
        .catch(() => { if (!cancelled && !controller.signal.aborted) setFailed(true); })
        .finally(() => {
          if (!cancelled) {
            setLoading(false);
            setResolved({ query: normalized, page, scope });
            nextRequestedRef.current = false;
          }
        });
    }, normalized ? 300 : 0);
    return () => { cancelled = true; window.clearTimeout(timer); controller.abort(); };
  }, [resourceId, resourceType, normalized, blocked, page, attempt, scope]);

  const loadNext = useCallback(() => {
    if (busy || failed || !hasMore || nextRequestedRef.current) return;
    nextRequestedRef.current = true;
    setPage((current) => current + 1);
  }, [busy, failed, hasMore]);
  const sentinelCallback = useCallback((node: HTMLDivElement | null) => {
    observerRef.current?.disconnect();
    if (!node || !scrollRef.current) return;
    observerRef.current = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) loadNext();
    }, { root: scrollRef.current, rootMargin: "100px" });
    observerRef.current.observe(node);
  }, [loadNext]);
  useEffect(() => () => observerRef.current?.disconnect(), []);

  const selectedIds = new Set(value.filter((s) => s.type === "user").map((s) => s.id));
  const disabledIdSet = new Set(disabledIds);

  const toggle = (user: UserRow) => {
    if (busy || failed || disabledIdSet.has(user.user_id)) return;
    if (selectedIds.has(user.user_id)) {
      onChange(value.filter((s) => s.type !== "user" || s.id !== user.user_id));
    } else {
      onChange([
        ...value,
        { type: "user", id: user.user_id, name: user.user_name, externalId: user.external_id, departmentPath: user.primary_department_path },
      ]);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="relative shrink-0">
        <SearchInput
          clearLabel={localize("com_ui_clear")}
          placeholder={localize("com_permission.search_user")}
          value={keyword}
          onChange={(event) => { setKeyword(event.target.value); setPage(1); nextRequestedRef.current = false; }}
          onCompositionStart={input.onCompositionStart}
          onCompositionEnd={(event) => { input.onCompositionEnd(event); setPage(1); }}
          onPaste={(event) => { input.onPaste(event); setPage(1); }}
          aria-invalid={tooLong}
          className="w-full"
        />
      </div>
      {tooLong && <p role="alert" className="text-caption text-danger">{localize("com_permission.search_too_long")}</p>}
      <div
        ref={scrollRef}
        className="scrollbar-os min-h-0 flex-1 overflow-y-auto rounded-md border border-border-base"
      >
        {busy && !blocked && (
          <div className="py-4 text-center text-sm text-text-3">
            {localize("com_ui_loading")}
          </div>
        )}
        {!busy && failed && <div className="flex flex-col items-center gap-2 py-4 text-body-sm text-text-3"><span>{localize("com_permission.load_failed")}</span><Button size="small" color="default" variant="outlined" onClick={() => setAttempt((current) => current + 1)}>{localize("com_ui_retry")}</Button></div>}
        {!busy && !failed && results.length === 0 && (
          <PermissionEmptyState message={localize("com_permission.empty_search")} />
        )}
        {!busy && !failed && results.length > 0 && (
          <div className={PERMISSION_SUBJECT_LIST_CLASS}>
          {results.map((user) => {
            const isDisabled = disabledIdSet.has(user.user_id);
            const grantedLabel = grantedLabels[String(user.user_id)];
            // User id (external_id) renders right after the username; the dedicated
            // column shows only the org/department path.
            const departmentPath = user.primary_department_path ?? "";

            return (
              <div
                key={user.user_id}
                className={cn(
                  PERMISSION_SUBJECT_ROW_CLASS,
                  isDisabled
                    ? PERMISSION_SUBJECT_ROW_DISABLED_CLASS
                    : PERMISSION_SUBJECT_ROW_INTERACTIVE_CLASS,
                )}
                style={{ paddingLeft: permissionSubjectIndent(0) }}
                onClick={() => toggle(user)}
              >
                {/* No switcher slot: this list is flat, so nothing in it expands and
                    the slot would only be dead space. The checkbox leads the row. */}
                <div className={PERMISSION_SUBJECT_SLOT_CLASS}>
                  <Checkbox
                    className="peer border-[#D9D9D9] data-[state=checked]:border-primary data-[state=indeterminate]:border-primary"
                    // Already-granted rows read as checked: the picker shows who holds
                    // the resource, so an empty box next to the badge reads as a bug.
                    checked={selectedIds.has(user.user_id) || isDisabled}
                    disabled={isDisabled}
                  />
                </div>
                {/* Icon slot: 20×20 wrapper, 16×16 user icon — same column as the
                    department tab's entity icon. */}
                <div className={PERMISSION_SUBJECT_SLOT_CLASS}>
                  <Outlined.People className={PERMISSION_SUBJECT_ICON_CLASS} />
                </div>
                {/* Name column: username + user id (external_id) after it; the next
                    column shows only the org/department path. */}
                <div className="flex min-w-0 flex-1 items-center gap-1.5 pl-1">
                  <span className="min-w-0 truncate" title={user.user_name}>{user.user_name}</span>
                  <SubjectIdentity type="user" externalId={user.external_id} />
                  {/* "Already granted" badge sits right after the name/id; it stays at
                      full width while the username truncates, so it never crowds the
                      department column on the right. */}
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
                <span className="max-w-[45%] shrink-0 truncate text-xs text-text-3" title={departmentPath}>{departmentPath}</span>
              </div>
            );
          })}
          </div>
        )}
        {!busy && !failed && hasMore && (
          <div ref={sentinelCallback} className="py-2 text-center text-caption text-text-3">
            {localize("com_permission.load_more")}
          </div>
        )}
      </div>
    </div>
  );
}
