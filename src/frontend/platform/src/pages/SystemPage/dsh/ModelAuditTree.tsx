import { Button } from "@/components/bs-ui/button";
import type { AuditTreeNode, ModelAuditQuery } from "@/types/dshModelAudit";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { DshPager, dshTime } from "./common";
import { ModelAuditGroupRequests } from "./ModelAuditGroup";
import { useModelAuditTree } from "./useModelAuditTree";

interface ModelAuditTreeProps {
  node: AuditTreeNode;
  query: ModelAuditQuery;
  expanded: boolean;
  onToggle: () => void;
  onNavigate: (userId: number, conversationId: string) => void;
  onRefresh: () => void;
  depth?: number;
}

export function ModelAuditTree({
  node,
  query,
  expanded,
  onToggle,
  onNavigate,
  onRefresh,
  depth = 0,
}: ModelAuditTreeProps) {
  const { t } = useTranslation();
  const id = useId();
  const prefix = "dsh.modelAuditView.tree.";
  const abnormal =
    node.branch_summary.known_abnormal ||
    (node.branch_summary.abnormal_count || 0) > 0;
  const ready = node.branch_summary.ready;
  const reason = !["MAIN", "UNKNOWN", "LINKED"].includes(node.relation_state);
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
          {expanded ? (
            <ChevronDown className="mr-1 h-4 w-4 shrink-0" aria-hidden="true" />
          ) : (
            <ChevronRight
              className="mr-1 h-4 w-4 shrink-0"
              aria-hidden="true"
            />
          )}
          {node.user_name || t("dsh.modelAuditView.user_unavailable")} ·{" "}
          {node.conversation_id}
        </Button>
        {depth > 0 && (
          <span>{t(prefix + "child_level", { level: depth })}</span>
        )}
        <span>
          {t("dsh.modelAuditView.group_last")}: {dshTime(node.last_request_at)}
        </span>
        <span>
          {node.own_summary.ready
            ? t(prefix + "own_count", {
                count: Number(node.own_summary.request_count),
              })
            : t(prefix + "summary_pending")}
        </span>
        {node.has_children && (
          <span>
            {node.branch_summary.ready
              ? t(prefix + "branch_count", {
                  count: Number(node.branch_summary.request_count),
                })
              : t(prefix + "branch_pending")}
          </span>
        )}
        <span
          className={
            abnormal
              ? "text-destructive"
              : ready
                ? "text-success-foreground"
                : "text-muted-foreground"
          }
        >
          {abnormal
            ? ready
              ? t("dsh.modelAuditView.group_abnormal", {
                  count: Number(node.branch_summary.abnormal_count),
                })
              : t(prefix + "known_abnormal")
            : ready
              ? t("dsh.modelAuditView.summary.NORMAL")
              : t(prefix + "summary_pending")}
        </span>
      </header>
      {expanded && (
        <div
          id={id}
          className={
            "min-w-0 space-y-3 border-t py-3 " + (depth < 3 ? "px-3" : "")
          }
        >
          {reason && (
            <p className="break-words px-1 text-xs text-muted-foreground">
              {t(prefix + "reasons." + node.relation_state)}
            </p>
          )}
          {node.match_scope === "DESCENDANT" ? (
            <p className="text-xs text-muted-foreground">
              {t(prefix + "path_only")}
            </p>
          ) : (
            <>
              <h3 className="text-sm font-medium">
                {t(prefix + "own_requests")}
              </h3>
              <p className="text-xs text-muted-foreground">
                {t("dsh.modelAuditView.group_scope")}
              </p>
              <ModelAuditGroupRequests
                key={JSON.stringify(query)}
                group={node}
                query={query}
                onNavigate={onNavigate}
              />
            </>
          )}
          {node.has_children && (
            <section
              className="min-w-0 space-y-3 border-t pt-3"
              aria-label={t(prefix + "children")}
            >
              <h3 className="text-sm font-medium">{t(prefix + "children")}</h3>
              {depth >= 31 ? (
                <Button
                  type="button"
                  variant="link"
                  onClick={() => onNavigate(node.user_id, node.conversation_id)}
                >
                  {t(prefix + "continue")}
                </Button>
              ) : (
                <TreeChildren
                  key={JSON.stringify([
                    query,
                    node.generation,
                    node.conversation_key,
                  ])}
                  node={node}
                  query={query}
                  depth={depth}
                  onNavigate={onNavigate}
                  onRefresh={onRefresh}
                />
              )}
            </section>
          )}
        </div>
      )}
    </article>
  );
}

interface TreeChildrenProps {
  node: AuditTreeNode;
  query: ModelAuditQuery;
  depth: number;
  onNavigate: ModelAuditTreeProps["onNavigate"];
  onRefresh: () => void;
}

function TreeChildren({
  node,
  query,
  depth,
  onNavigate,
  onRefresh,
}: TreeChildrenProps) {
  const { t } = useTranslation();
  const state = useModelAuditTree(
    query,
    node.conversation_key,
    node.generation,
  );
  const [open, setOpen] = useState<string | null>(null);
  const refresh = state.page?.progress.refresh_required;
  const prefix = "dsh.modelAuditView.tree.";
  return (
    <>
      {state.failed || refresh ? (
        <div role="alert" className="space-y-2 text-sm">
          <p>
            {t(
              refresh
                ? prefix + "refresh_required"
                : "dsh.modelAuditView.loadError",
            )}
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={refresh ? onRefresh : state.onRetry}
          >
            {t(prefix + "retry")}
          </Button>
        </div>
      ) : state.loading ? (
        <p role="status">{t("dsh.loading")}</p>
      ) : (
        <>
          {state.page?.scan_limited && (
            <p role="status" className="text-xs text-muted-foreground">
              {t("dsh.modelAuditView.scan_limited")}
            </p>
          )}
          {!state.page?.items.length && !state.page?.next_cursor && (
            <p className="text-xs text-muted-foreground">
              {t(prefix + "no_children")}
            </p>
          )}
          {state.page?.items.map((child) => (
            <ModelAuditTree
              key={child.conversation_key}
              node={child}
              query={query}
              depth={depth + 1}
              expanded={open === child.conversation_key}
              onToggle={() =>
                setOpen((old) =>
                  old === child.conversation_key
                    ? null
                    : child.conversation_key,
                )
              }
              onNavigate={onNavigate}
              onRefresh={onRefresh}
            />
          ))}
        </>
      )}
      <DshPager
        previous={state.previous}
        next={!!state.page?.next_cursor}
        loading={state.loading}
        onPrevious={() => {
          setOpen(null);
          state.onPrevious();
        }}
        onNext={() => {
          setOpen(null);
          state.onNext();
        }}
      />
    </>
  );
}
