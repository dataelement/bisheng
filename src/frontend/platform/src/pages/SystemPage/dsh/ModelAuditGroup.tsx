import { Button } from "@bisheng/ui";
import "@/style/dsh-content-safety.css";
import { Badge, Tag } from "@bisheng/ui";
import type {
  AuditConversation,
  AuditMessageFeedback,
  AuditQueryReadiness,
  ModelAuditPage,
  ModelAuditQuery,
} from "@/types/dshModelAudit";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { DshPager, dshTime } from "./common";
import { ModelAuditCard } from "./ModelAuditCard";
import { useModelAudit } from "./useModelAudit";

const feedbackCategories = [
  "task-result",
  "instruction-following",
  "product-interaction",
  "service-stability",
  "resource-cost",
  "security-privacy-permission",
  "other",
];

export function ModelAuditFeedbackCounts({
  likeCount,
  dislikeCount,
}: {
  likeCount?: number;
  dislikeCount?: number;
}) {
  const { t } = useTranslation();
  if (!knownSafetyCount(likeCount) || !knownSafetyCount(dislikeCount)) return null;
  return (
    <>
      {likeCount > 0 && (
        <span>{t("dsh.modelAuditView.group_likes", { count: likeCount })}</span>
      )}
      {dislikeCount > 0 && (
        <span>{t("dsh.modelAuditView.group_dislikes", { count: dislikeCount })}</span>
      )}
    </>
  );
}

interface ModelAuditGroupProps {
  group: AuditConversation;
  progress?: AuditQueryReadiness;
  query: ModelAuditQuery;
  expanded: boolean;
  onToggle: () => void;
}
export function ModelAuditGroup({
  group,
  progress,
  query,
  expanded,
  onToggle,
}: ModelAuditGroupProps) {
  const { t } = useTranslation();
  const id = useId();
  const summaryReady =
    progress?.status_ready === true &&
    progress.name_ready === true &&
    progress.indexing_pending === false;
  return (
    <article className="min-w-0 overflow-hidden rounded-xl border">
      <header className="flex flex-wrap items-center gap-2 bg-muted/30 px-4 py-2 text-xs text-muted-foreground">
        <Button
          type="button"
          variant="text" color="default"
          size="small"
          className="h-auto min-h-8 w-full min-w-0 flex-none justify-start whitespace-normal break-all text-left text-sm md:w-auto md:flex-1 [@media(pointer:coarse)]:min-h-11"
          aria-expanded={expanded}
          aria-controls={expanded ? id : undefined}
          onClick={onToggle}
        >
          {expanded ? "▾ " : "▸ "}
          {group.user_name || t("dsh.modelAuditView.user_unavailable")} ·{" "}
          <span title={group.conversation_id}>{group.conversation_title || group.conversation_id}</span>
        </Button>
        <span>
          {t("dsh.modelAuditView.group_last")}: {dshTime(group.last_request_at)}
        </span>
        {summaryReady && (
          <>
            <span>
              {t("dsh.modelAuditView.group_count", { count: group.request_count })}
            </span>
            <ModelAuditFeedbackCounts
              likeCount={group.like_count}
              dislikeCount={group.dislike_count}
            />
            <span className={group.abnormal_count ? "text-destructive" : "text-success-foreground"}>
              {group.abnormal_count
                ? t("dsh.modelAuditView.group_abnormal", { count: group.abnormal_count })
                : t("dsh.modelAuditView.summary.NORMAL")}
            </span>
          </>
        )}
      </header>
      <ModelAuditSafetySummary
        progress={progress}
        own={{
          label: "all_hits",
          ready: progress?.safety_ready,
          count: group.sensitive_hit_count,
          hasHit: group.has_sensitive_hit,
        }}
        matchingCount={group.matching_sensitive_hit_count}
      />
      {expanded && (
        <div id={id} className="space-y-3 border-t p-3">
          <p className="text-xs text-muted-foreground">
            {t("dsh.modelAuditView.group_scope")}
          </p>
          <ModelAuditGroupRequests
            key={JSON.stringify(query)}
            group={group}
            query={query}
          />
        </div>
      )}
    </article>
  );
}

type SafetyCount = {
  label: "all_hits" | "own_hits" | "branch_hits";
  count?: number | null;
  ready?: boolean;
  hasHit?: boolean;
};
interface ModelAuditSafetySummaryProps {
  progress?: AuditQueryReadiness;
  own: SafetyCount;
  branch?: SafetyCount;
  matchingCount?: number | null;
}
function knownSafetyCount(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

export function ModelAuditSafetySummary({
  progress,
  own,
  branch,
  matchingCount,
}: ModelAuditSafetySummaryProps) {
  const { t } = useTranslation();
  const prefix = "dsh.contentSafety.readiness.";
  const counts = branch ? [own, branch] : [own];
  const available = (value: SafetyCount) =>
    progress?.safety_ready === true &&
    value.ready === true &&
    knownSafetyCount(value.count);
  const ready = counts.every(available);
  const knownHit = counts.some((value) =>
    value.hasHit === true || (knownSafetyCount(value.count) && value.count > 0),
  );
  if (!ready) return null;
  const watermark = progress?.safety_summary_as_of;
  return (
    <div className="dsh-content-safety">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2 text-xs text-text-2">
        {counts.filter(available).map((value) => (
          <span key={value.label} className="inline-flex items-center gap-2">
            {t(prefix + value.label)}
            <Badge
              count={value.count ?? undefined}
              showZero
              color="brand"
              aria-label={t(prefix + value.label) + ": " + value.count}
            />
          </span>
        ))}
        {knownSafetyCount(matchingCount) && (
          <span className="inline-flex items-center gap-2">
            {t(prefix + "matching_hits")}
            <Badge
              count={matchingCount}
              showZero
              color="brand"
              aria-label={t(prefix + "matching_hits") + ": " + matchingCount}
            />
          </span>
        )}
        <span>
          <Tag size="small" color="success">
            {t(prefix + "ready")}
          </Tag>
        </span>
        {knownHit && (
          <Tag size="small" color="danger">
            {t("dsh.contentSafety.states.BLOCKED")}
          </Tag>
        )}
        {watermark && !Number.isNaN(Date.parse(watermark)) && (
          <time dateTime={watermark}>
            {t(prefix + "as_of", { time: dshTime(watermark) })}
          </time>
        )}
      </div>
    </div>
  );
}

interface GroupRequestsProps {
  group: AuditConversation;
  query: ModelAuditQuery;
}
export function ModelAuditGroupRequests({
  group,
  query,
}: GroupRequestsProps) {
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
  const feedback = messageFeedback(page ?? undefined);
  return (
    <>
      {feedback.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-sm font-medium">
            {t("dsh.modelAuditView.feedback_heading")}
          </h3>
          <ul className="space-y-2">
            {feedback.map((item) => (
              <li key={item.message_id} className="break-all text-xs text-muted-foreground">
                <span>{item.message_id}</span>
                {item.rating && (
                  <span>
                    {" "}
                    {t("dsh.modelAuditView.feedback.rating." + item.rating)}
                  </span>
                )}
                {item.category && feedbackCategories.includes(item.category) && (
                  <span>
                    {" "}
                    {t("dsh.modelAuditView.feedback.category." + item.category)}
                  </span>
                )}
                {item.note && <p className="mt-1 whitespace-pre-wrap break-all">{item.note}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}
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

function messageFeedback(page?: ModelAuditPage): AuditMessageFeedback[] {
  if (!Array.isArray(page?.message_feedback)) return [];
  return page.message_feedback.filter(
    (item): item is AuditMessageFeedback & { message_id: string } =>
      typeof item?.message_id === "string" && item.message_id.length > 0,
  );
}
