import type { UseTaskWorkspaceStateOptions } from "./chatSurfaceTypes";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useUnactivate } from "react-activation";
import { useWorkspacePanel } from "~/components/Linsight/Artifacts/useWorkspacePanel";
import { useCompareTransitionFreeze } from "~/components/Linsight/Artifacts/useCompareTransitionFreeze";
import {
  collectConversationWorkspaceFiles,
  getWorkspaceLoadState,
} from "~/components/Linsight/Artifacts/artifactUtils";
import { useLinsightManager } from "~/hooks/useLinsightManager";
import { SopStatus } from "~/store/linsight";
import {
  findPendingUserInput,
  splitSessionPseudoTask,
} from "~/components/Linsight/Execution/stepUtils";
import type { ExecStepEventData } from "~/components/Linsight/Execution/stepUtils";
import { collectChatAttachments } from "../attachments/collectChatAttachments";

export function useTaskWorkspaceState({
  conversationId,
  messages,
  chatContainerRef,
  isCompactLayout,
  closeCitationPanel,
  taskVersionIds,
  latestTaskVersionId,
}: UseTaskWorkspaceStateOptions) {
  const { getLinsight, updateLinsight, linsightMap } = useLinsightManager();
  const taskArtifacts = useWorkspacePanel(latestTaskVersionId, conversationId);
  const chatAttachments = useMemo(
    () => collectChatAttachments(messages),
    [messages],
  );

  // F035: enter/exit animation for the fullscreen workspace overlay. The overlay
  // is a separate instance from the docked panel (only one is ever mounted at a
  // time). It's portaled to document.body + position:fixed so it can escape
  // chatContainer and cover the sidebar conversation list. It expands to fill the
  // rounded content card (the white panel inside <main>'s gutter that holds the
  // sidebar + chat) — NOT the whole window — so the icon rail and the card's
  // surrounding gap + radius are preserved. `fsMounted` keeps it in the DOM
  // across the collapse transition; `fsExpanded` drives the geometry between the
  // docked card's box and the content card's box, both measured in viewport-inset
  // form on enter (still mounted that render). Exiting: collapse, unmount on end.
  const dockedCardRef = useRef<HTMLDivElement>(null);
  const compareFreeze = useCompareTransitionFreeze(
    taskArtifacts.comparing,
    taskArtifacts.open,
    !isCompactLayout,
    dockedCardRef,
  );
  const { fullscreen, setFullscreen } = taskArtifacts;
  const [fsMounted, setFsMounted] = useState(false);
  const [fsExpanded, setFsExpanded] = useState(false);
  type FsInset = { top: number; left: number; right: number; bottom: number };
  const [fsBox, setFsBox] = useState<{
    collapsed: FsInset;
    expanded: FsInset;
  } | null>(null);
  useEffect(() => {
    if (fullscreen) {
      // Measure the docked card (collapsed) and <main> (expanded) in viewport-inset
      // coords. Both are still in the DOM this render (card gated on !fsMounted,
      // flipped just below). Inset form lets us animate to <main>'s edges cleanly.
      const card = dockedCardRef.current;
      // Climb to the OUTERMOST <main>: Presentation wraps ChatView in its own
      // <main> (chat content only), but MainLayout's outer <main> is the one that
      // also contains the sidebar conversation list — that's the box to fill.
      let main =
        card?.closest("main") ??
        chatContainerRef.current?.closest("main") ??
        null;
      for (
        let p = main?.parentElement?.closest("main");
        p;
        p = p.parentElement?.closest("main")
      ) {
        main = p;
      }
      if (card && main) {
        const W = window.innerWidth;
        const H = window.innerHeight;
        const c = card.getBoundingClientRect();
        const m = main.getBoundingClientRect();
        // Collapsed = the docked panel's measured box (it keeps its 4px p-1 margin),
        // overlay padding 0. Expanded grows the BOX outward by 4px on top/right/
        // bottom (border reaches the card edge) and left to the card's left
        // (main.left + 8px p-2 gutter), while the overlay's padding goes 0 → 4px.
        // Net: the inner content (toolbar buttons) stays at the exact docked
        // position the whole time — only the gray border slides out to the card edge
        // and the left edge fills the card. No button shift, smooth border, uniform
        // #FBFBFB fill (the 4px is overlay bg, not a white ring).
        // The content card sits inside <main>'s content box, so its left edge is
        // main.left + main's (possibly-asymmetric / zero) left padding. Read it live
        // instead of hardcoding so changing the layout gutter never desyncs the
        // fullscreen left edge.
        const mainPadLeft = parseFloat(getComputedStyle(main).paddingLeft) || 0;
        const collapsed = {
          top: c.top,
          left: c.left,
          right: W - c.right,
          bottom: H - c.bottom,
        };
        setFsBox({
          collapsed,
          expanded: {
            top: collapsed.top - 4,
            right: collapsed.right - 4,
            bottom: collapsed.bottom - 4,
            left: m.left + mainPadLeft,
          },
        });
      }
      setFsMounted(true);
      // Double rAF: let the collapsed state paint before flipping to expanded,
      // otherwise React can batch both and the enter transition is skipped.
      let r2 = 0;
      const r1 = requestAnimationFrame(() => {
        r2 = requestAnimationFrame(() => setFsExpanded(true));
      });
      return () => {
        cancelAnimationFrame(r1);
        cancelAnimationFrame(r2);
      };
    }
    setFsExpanded(false);
    // Fallback unmount in case transitionEnd never fires (e.g. reduced-motion
    // disables the transition) — otherwise the overlay would stay mounted and the
    // docked panel would never re-render. Slightly longer than the 300ms anim.
    const t = setTimeout(() => setFsMounted(false), 360);
    return () => clearTimeout(t);
  }, [fullscreen, chatContainerRef]);

  // F035: the fullscreen overlay is desktop-only. Resizing into the touch layout
  // (≤1023px) while it's open would otherwise leave `fullscreen` true with the
  // overlay suppressed; clear it so the mobile overlay/drawer branch renders.
  useEffect(() => {
    if (isCompactLayout && fullscreen) {
      setFullscreen(false);
    }
  }, [isCompactLayout, fullscreen, setFullscreen]);

  // KeepAlive freezes (but doesn't unmount) ChatView when the user switches to
  // another sidebar section, so the <body>-portaled fullscreen overlay would keep
  // floating over the new page. Collapse the workspace + force-unmount the overlay
  // on deactivate so the new section is shown unobstructed.
  useUnactivate(() => {
    taskArtifacts.closeWorkspace();
    setFsExpanded(false);
    setFsMounted(false);
    // The citation panel portals to <body> in the 768–1023 / mobile tiers, so it
    // also outlives the cached view — collapse it so it doesn't hang over the
    // section the user switched to.
    closeCitationPanel();
  });

  const taskLinsight = latestTaskVersionId
    ? getLinsight(latestTaskVersionId)
    : null;
  const taskWorkspaceFiles = useMemo(() => {
    return collectConversationWorkspaceFiles(
      taskVersionIds.map((versionId) => ({ versionId, snapshot: linsightMap.get(versionId) })),
    );
  }, [taskVersionIds, linsightMap]);
  // Task turns hydrate lazily (TaskTurnPanel), so on a cold load (share page,
  // full refresh) the store is still empty — that must not read as "no files".
  // A turn whose load failed reports it here; it never reaches the store.
  const [taskLoadFailedIds, setTaskLoadFailedIds] = useState<
    ReadonlySet<string>
  >(() => new Set());
  const reportTaskTurnLoadFailed = useCallback(
    (versionId: string, failed: boolean) => {
      setTaskLoadFailedIds((prev) => {
        if (prev.has(versionId) === failed) return prev;
        const next = new Set(prev);
        if (failed) next.add(versionId);
        else next.delete(versionId);
        return next;
      });
    },
    [],
  );
  const taskWorkspaceLoadState = useMemo(
    () => getWorkspaceLoadState(taskVersionIds, linsightMap, taskLoadFailedIds),
    [taskVersionIds, linsightMap, taskLoadFailedIds],
  );

  // F035: while the latest task round is in a non-terminal state (generating /
  // running / queued), the input stays editable but the send button is disabled
  // — the next round can only be submitted after the current one finishes.
  const taskRunning = useMemo(() => {
    const status = taskLinsight?.status;
    return (
      status === SopStatus.NotStarted ||
      status === SopStatus.SopGenerating ||
      status === SopStatus.SopGenerated ||
      status === SopStatus.Running
    );
  }, [taskLinsight]);

  // A parked task (ask_user awaiting the user's reply) keeps status === Running —
  // park is not a distinct live status — so taskRunning stays true even though the
  // agent is suspended on an interrupt and nothing is executing. Detect the park
  // (an unanswered call_user_input in the latest task turn) so the input can drop
  // the misleading "running" Stop button and show a "waiting for your reply" hint;
  // the user answers via the ClarifyCard in the message stream, not this input.
  const awaitingUserInput = useMemo(() => {
    if (!taskRunning || !taskLinsight) return false;
    const { tasks, sessionSteps } = splitSessionPseudoTask(
      (taskLinsight.tasks as Parameters<typeof splitSessionPseudoTask>[0]) ||
        [],
      (taskLinsight.sessionSteps as ExecStepEventData[]) || [],
    );
    return !!findPendingUserInput(sessionSteps, tasks);
  }, [taskRunning, taskLinsight]);

  return {
    updateLinsight,
    taskArtifacts,
    chatAttachments,
    dockedCardRef,
    compareFreeze,
    fsMounted,
    setFsMounted,
    fsExpanded,
    fsBox,
    taskLinsight,
    taskWorkspaceFiles,
    reportTaskTurnLoadFailed,
    taskWorkspaceLoadState,
    taskRunning,
    awaitingUserInput,
  };
}
