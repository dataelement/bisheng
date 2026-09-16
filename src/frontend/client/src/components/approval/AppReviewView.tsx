import { Tabs, Tag } from "@bisheng/ui";
import { VersionDiffView } from "@bisheng/file-viewers";
import { Outlined } from "bisheng-icons";
import { useEffect, useState } from "react";
import {
  getReviewContextApi,
  getSnapshotTreeApi,
  getVersionDiffApi,
  type ReviewContext,
  type SnapshotTree,
  type VersionDiffResponse,
} from "~/api/hostedAppReview";
import type { LocalizeFn } from "./approvalPresentation";
import { formatTime } from "./approvalPresentation";
import { ReviewSourcePane } from "./ReviewSourcePane";

/**
 * The review view (F055 AC-25): what an approver reads before deciding.
 *
 * Reached from 「查看待上线版本」 on the app-publish approval card, and it takes
 * over the whole settings content panel rather than opening a second surface —
 * design D14's 案 A, restated for the page the approval centre became: the
 * decision stays where the approver already is, and 「返回」 puts the two-column
 * list back.
 *
 * Four tabs, and the tab is what decides which read runs: source browsing, the
 * capability declaration in full, the version history, and the diff against
 * the last published version. Nothing here can change anything — approve and
 * reject stay on the card behind 「返回」, because a decision taken while
 * reading code is a decision taken without the request in front of you.
 */

type ReviewTab = "source" | "capabilities" | "versions" | "diff";

/** One declared capability, in the shape `build_detail` ships it. */
export interface ReviewCapability {
  type: string;
  name: string;
  description: string;
}

/**
 * Everything the view needs that the approval card has already parsed out of
 * `detail_snapshot`. Passing it through keeps one parser for that payload —
 * the card — instead of two that can disagree about the same release.
 */
export interface AppReviewTarget {
  appId: string;
  versionId: string;
  appName: string;
  versionNo: number | null;
  releaseKindText: string;
  capabilities: ReviewCapability[];
}

export interface AppReviewViewProps {
  target: AppReviewTarget;
  localize: LocalizeFn;
  onBack: () => void;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "";
}

export function AppReviewView({ target, localize, onBack }: AppReviewViewProps) {
  const { appId, versionId, appName, versionNo, releaseKindText, capabilities } = target;
  const [tab, setTab] = useState<ReviewTab>("source");
  const [context, setContext] = useState<ReviewContext | null>(null);
  const [tree, setTree] = useState<SnapshotTree | null>(null);
  const [diff, setDiff] = useState<VersionDiffResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState("");
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffFailure, setDiffFailure] = useState("");

  // The tree and the context are what the header and three of the four tabs
  // need, so both are read once on open rather than per tab switch.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFailure("");
    Promise.all([getSnapshotTreeApi(appId, versionId), getReviewContextApi(appId, versionId)])
      .then(([treeData, contextData]) => {
        if (cancelled) return;
        setTree(treeData);
        setContext(contextData);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setTree(null);
        setContext(null);
        setFailure(errorText(error));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [appId, versionId]);

  // AC-41's comparison, and only that one: the version waiting to go live
  // against the one currently published. There is no version picker here —
  // an approver is deciding on one release, not browsing history.
  const baseVersionId = context?.current_version_id ?? null;
  const hasBaseline = !!baseVersionId && baseVersionId !== versionId;

  useEffect(() => {
    if (tab !== "diff" || !hasBaseline || !baseVersionId || diff) return;
    let cancelled = false;
    setDiffLoading(true);
    setDiffFailure("");
    getVersionDiffApi(appId, baseVersionId, versionId)
      .then((data) => {
        if (!cancelled) setDiff(data);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setDiff(null);
        setDiffFailure(errorText(error));
      })
      .finally(() => {
        if (!cancelled) setDiffLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tab, hasBaseline, baseVersionId, appId, versionId, diff]);

  const tabItems = [
    { key: "source", label: localize("com_approval_review_tab_source") },
    { key: "capabilities", label: localize("com_approval_review_tab_capabilities") },
    { key: "versions", label: localize("com_approval_review_tab_versions") },
    { key: "diff", label: localize("com_approval_review_tab_diff") },
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="app-review-view">
      <div className="flex shrink-0 items-center gap-3 border-b border-fill-2 px-5 py-3">
        <button
          type="button"
          onClick={onBack}
          className="flex shrink-0 items-center gap-1.5 text-[13px] text-text-2 hover:text-text-primary"
        >
          <Outlined.ArrowLeft className="size-4" />
          {localize("com_approval_review_back")}
        </button>
        <span className="h-4 w-px shrink-0 bg-fill-3" />
        <h3 className="min-w-0 flex-1 truncate text-base font-semibold text-text-primary">{appName}</h3>
        {versionNo ? (
          <Tag size="small" className="shrink-0 whitespace-nowrap">{`v${versionNo}`}</Tag>
        ) : null}
        {releaseKindText ? (
          <span className="shrink-0 text-[12px] text-text-3">{releaseKindText}</span>
        ) : null}
      </div>

      <div className="px-5 pt-2">
        <Tabs
          size="medium"
          variant="neutral"
          divider={false}
          items={tabItems}
          activeKey={tab}
          onChange={(key) => setTab(key as ReviewTab)}
        />
      </div>

      <div className="scrollbar-os flex min-h-0 flex-1 flex-col overflow-y-auto px-5 pb-5 pt-3">
        {loading ? (
          <p className="text-[13px] text-text-3">{localize("com_approval_review_loading")}</p>
        ) : failure ? (
          <p className="text-[13px] text-text-3">{failure}</p>
        ) : tab === "source" ? (
          <ReviewSourcePane
            appId={appId}
            versionId={versionId}
            entries={tree?.entries ?? []}
            truncated={tree?.truncated ?? false}
            localize={localize}
          />
        ) : tab === "capabilities" ? (
          capabilities.length === 0 ? (
            <p className="text-[13px] text-text-3">
              {localize("com_approval_app_publish_capabilities_empty")}
            </p>
          ) : (
            <ul className="overflow-hidden rounded-lg border border-fill-2">
              {capabilities.map((capability, index) => (
                <li
                  key={`${capability.type}-${capability.name}-${index}`}
                  className="border-b border-fill-2 bg-white px-3 py-2 last:border-b-0"
                >
                  <div className="text-[14px] font-medium text-text-primary break-all">
                    {capability.name || "--"}
                  </div>
                  {(capability.type || capability.description) && (
                    <div className="mt-0.5 text-[12px] text-text-3 break-all">
                      {[capability.type, capability.description].filter(Boolean).join(" · ")}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )
        ) : tab === "versions" ? (
          <ul className="overflow-hidden rounded-lg border border-fill-2">
            {(context?.versions ?? []).map((row) => (
              <li
                key={row.version_id}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-fill-2 bg-white px-3 py-2 text-[13px] last:border-b-0"
              >
                <span className="font-medium text-text-primary">{`v${row.version_no}`}</span>
                <span className="text-text-3">
                  {localize(
                    row.kind === "initial"
                      ? "com_approval_app_publish_kind_initial"
                      : "com_approval_app_publish_kind_iteration",
                  )}
                </span>
                <span className="text-text-3">{formatTime(row.submitted_at)}</span>
                {row.terminal_state && (
                  <span className="text-text-3">
                    {localize(`com_approval_review_terminal_${row.terminal_state}`)}
                  </span>
                )}
                {row.is_current && (
                  <Tag size="small" color="success" className="shrink-0 whitespace-nowrap">
                    {localize("com_approval_review_version_current")}
                  </Tag>
                )}
                {row.is_pending && (
                  <Tag size="small" color="approving" className="shrink-0 whitespace-nowrap">
                    {localize("com_approval_review_version_pending")}
                  </Tag>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <VersionDiffView
            summary={diff?.summary ?? null}
            files={diff?.files ?? []}
            patches={diff?.patches ?? []}
            caption={
              diff ? `v${diff.base.version_no} → v${diff.target.version_no}` : undefined
            }
            loading={diffLoading}
            errorMessage={diffFailure || undefined}
            emptyMessage={hasBaseline ? undefined : localize("com_approval_review_no_baseline")}
          />
        )}
      </div>
    </div>
  );
}
