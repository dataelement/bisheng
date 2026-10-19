import { Button } from "@/components/bs-ui/button";
import type { AuditConversation, ModelAuditQuery } from "@/types/dshModelAudit";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { DshPager, dshTime } from "./common";
import { ModelAuditCard } from "./ModelAuditCard";
import { useModelAudit } from "./useModelAudit";

interface ModelAuditGroupProps {
  group: AuditConversation;
  query: ModelAuditQuery;
  expanded: boolean;
  onToggle: () => void;
  onNavigate: (userId: number, conversationId: string) => void;
}
export function ModelAuditGroup({
  group,
  query,
  expanded,
  onToggle,
  onNavigate,
}: ModelAuditGroupProps) {
  const { t } = useTranslation();
  const id = useId();
  return (
    <article className="min-w-0 overflow-hidden rounded-xl border">
      <header className="flex flex-wrap items-center gap-2 bg-muted/30 px-4 py-2 text-xs text-muted-foreground">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-auto min-h-8 w-full min-w-0 flex-none justify-start whitespace-normal break-all text-left text-sm md:w-auto md:flex-1 [@media(pointer:coarse)]:min-h-11"
          aria-expanded={expanded}
          aria-controls={expanded ? id : undefined}
          onClick={onToggle}
        >
          {expanded ? "▾ " : "▸ "}
          {t("dsh.modelAuditView.user")} #{group.user_id} ·{" "}
          {group.conversation_id}
        </Button>
        <span>
          {t("dsh.modelAuditView.group_last")}: {dshTime(group.last_request_at)}
        </span>
        <span>
          {t("dsh.modelAuditView.group_count", { count: group.request_count })}
        </span>
        <span
          className={
            group.abnormal_count
              ? "text-destructive"
              : "text-success-foreground"
          }
        >
          {group.abnormal_count
            ? t("dsh.modelAuditView.group_abnormal", {
                count: group.abnormal_count,
              })
            : t("dsh.modelAuditView.summary.NORMAL")}
        </span>
      </header>
      {expanded && (
        <div id={id} className="space-y-3 border-t p-3">
          <p className="text-xs text-muted-foreground">
            {t("dsh.modelAuditView.group_scope")}
          </p>
          <GroupRequests
            key={JSON.stringify(query)}
            group={group}
            query={query}
            onNavigate={onNavigate}
          />
          <Button
            type="button"
            variant="link"
            onClick={() => onNavigate(group.user_id, group.conversation_id)}
          >
            {t("dsh.modelAuditView.group_all")}
          </Button>
        </div>
      )}
    </article>
  );
}

interface GroupRequestsProps {
  group: AuditConversation;
  query: ModelAuditQuery;
  onNavigate: (userId: number, conversationId: string) => void;
}
function GroupRequests({ group, query, onNavigate }: GroupRequestsProps) {
  const { t } = useTranslation();
  const [cursor, setCursor] = useState<string>();
  const [history, setHistory] = useState<(string | undefined)[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [requestQuery, setRequestQuery] = useState<ModelAuditQuery>({
    ...query,
    cursor: undefined,
  });
  const { page, loading, failed } = useModelAudit(
    requestQuery,
    0,
    group.conversation_key,
  );
  const handlePage = (next?: string) => {
    setExpanded(null);
    setCursor(next);
    setRequestQuery({ ...query, cursor: next });
  };
  return (
    <>
      {failed ? (
        <p role="alert">{t("dsh.modelAuditView.loadError")}</p>
      ) : loading ? (
        <p role="status">{t("dsh.loading")}</p>
      ) : !page?.items.length ? (
        <p>{t("dsh.modelAuditView.empty")}</p>
      ) : (
        page.items.map((row) => (
          <ModelAuditCard
            key={row.request_id}
            row={row}
            tenantId={query.tenant_id}
            expanded={expanded === row.request_id}
            onToggle={() =>
              setExpanded((old) =>
                old === row.request_id ? null : row.request_id,
              )
            }
            onNavigate={onNavigate}
          />
        ))
      )}
      <DshPager
        previous={!!history.length}
        next={!!page?.next_cursor}
        loading={loading}
        onPrevious={() => {
          handlePage(history[history.length - 1]);
          setHistory((old) => old.slice(0, -1));
        }}
        onNext={() => {
          if (page?.next_cursor) {
            setHistory((old) => [...old, cursor]);
            handlePage(page.next_cursor);
          }
        }}
      />
    </>
  );
}
