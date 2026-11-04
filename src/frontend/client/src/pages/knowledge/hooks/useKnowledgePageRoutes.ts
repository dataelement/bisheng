import { useEffect } from "react";
import {
  KnowledgeSpace,
  SpaceRole,
  VisibilityType,
  getSpaceInfoApi,
  getMineSpacesApi,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { canOpenSharedSpace } from "../knowledgeUtils";
import { resolveSpaceInfoFailure } from "../spaceInfoError";
import type { KnowledgePageModel } from "../index";

export function useKnowledgePageRoutes({
  setActiveSpace,
  setShowKnowledgeSquare,
  navigate,
  localizeRef,
  showToastRef,
  navigateRef,
  location,
  previewSpaceId,
  detailSpaceId,
  setPreviewDrawerOpen,
  setSquarePreviewSpaceId,
  setSquarePreviewSpace,
  setSquarePreviewDrawerOpen,
  previewQueryCleanupTimerRef,
  knowledgeTabActivateEpoch,
  knowledgePluginGate,
}: Pick<
  KnowledgePageModel,
  | "setActiveSpace"
  | "setShowKnowledgeSquare"
  | "navigate"
  | "localizeRef"
  | "showToastRef"
  | "navigateRef"
  | "location"
  | "spaceId"
  | "path"
  | "previewSpaceId"
  | "detailSpaceId"
  | "setPreviewDrawerOpen"
  | "setSquarePreviewSpaceId"
  | "setSquarePreviewSpace"
  | "setSquarePreviewDrawerOpen"
  | "previewQueryCleanupTimerRef"
  | "knowledgeTabActivateEpoch"
  | "knowledgePluginGate"
  | "mineSpaces"
>) {
  // Share route: close drawer when leaving /knowledge/share/:spaceId
  useEffect(() => {
    if (!previewSpaceId) {
      setPreviewDrawerOpen(false);
    }
  }, [previewSpaceId, setPreviewDrawerOpen]);

  // Deep link to space detail: /knowledge/space/:spaceId or /knowledge/space/:spaceId/folder/:folderId
  useEffect(() => {
    if (!detailSpaceId) return;
    if (knowledgePluginGate === "loading" || knowledgePluginGate === "disabled")
      return;

    // Immediately claim the space ID so the sidebar auto-select won't
    // race ahead and pick a different space while the info fetch is in-flight.
    setActiveSpace((prev) =>
      prev?.id === detailSpaceId
        ? prev
        : ({ id: detailSpaceId } as KnowledgeSpace),
    );
    setShowKnowledgeSquare(false);
    setSquarePreviewDrawerOpen(false);
    setSquarePreviewSpaceId(undefined);

    let cancelled = false;
    (async () => {
      try {
        const detail = await getSpaceInfoApi(detailSpaceId);
        if (cancelled) return;
        // No membership redirect here, deliberately. The space page is itself the

        // list), and the desktop sidebar auto-selects the first department space
        // whenever nothing is active. Diverting a non-follower to the share
        // preview therefore looped: close the preview -> /knowledge -> auto-select
        // the same department space -> redirect -> preview again, with no way out.
        setActiveSpace({ ...detail, id: detailSpaceId });
      } catch (error) {
        if (cancelled) return;
        // Only a space the server says is absent or closed to this caller
        // sends the user away; anything else stays put (see spaceInfoError).
        const failure = resolveSpaceInfoFailure(error);
        showToastRef.current({
          message: failure.message || localizeRef.current(failure.messageKey),
          severity: NotificationSeverity.WARNING,
        });
        if (failure.leaveSpace) {
          navigateRef.current("/knowledge?square=1", { replace: true });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    detailSpaceId,
    knowledgePluginGate,
    knowledgeTabActivateEpoch,
    localizeRef,
    navigateRef,
    setActiveSpace,
    setShowKnowledgeSquare,
    setSquarePreviewDrawerOpen,
    setSquarePreviewSpaceId,
    showToastRef,
  ]);

  useEffect(() => {
    if (knowledgePluginGate === "loading" || knowledgePluginGate === "disabled")
      return;
    const path = location.pathname || "";
    const isSpaceDetailPath = /\/knowledge\/space\//.test(path);

    if (isSpaceDetailPath) {
      setShowKnowledgeSquare(false);
      const params = new URLSearchParams(location.search);
      if (params.get("square") === "1") {
        params.delete("square");
        const nextSearch = params.toString();
        navigate(nextSearch ? `${path}?${nextSearch}` : path, {
          replace: true,
        });
      }
      return;
    }

    const params = new URLSearchParams(location.search);
    if (params.get("square") === "1") {
      setShowKnowledgeSquare(true);
    }
    const previewFromQuery = params.get("previewSpace");
    if (previewFromQuery) {
      setShowKnowledgeSquare(true);
      setSquarePreviewSpaceId(previewFromQuery);
      setSquarePreviewDrawerOpen(true);
      if (previewQueryCleanupTimerRef.current) {
        clearTimeout(previewQueryCleanupTimerRef.current);
      }
      // Delay URL cleanup so state updates (open drawer + target id) land first.
      previewQueryCleanupTimerRef.current = setTimeout(() => {
        const cleanupParams = new URLSearchParams(location.search);
        cleanupParams.delete("previewSpace");
        const nextSearch = cleanupParams.toString();
        const basePath = path || "/knowledge";
        navigate(nextSearch ? `${basePath}?${nextSearch}` : basePath, {
          replace: true,
        });
        previewQueryCleanupTimerRef.current = null;
      }, 0);
    }
  }, [
    location.search,
    location.pathname,
    navigate,
    knowledgePluginGate,
    knowledgeTabActivateEpoch,
    previewQueryCleanupTimerRef,
    setShowKnowledgeSquare,
    setSquarePreviewDrawerOpen,
    setSquarePreviewSpaceId,
  ]);

  // Fallback for consecutive notification clicks in the same tab/session:
  // update square preview drawer immediately even when route diff is swallowed.
  useEffect(() => {
    const onPreviewFromNotification = (evt: Event) => {
      const customEvt = evt as CustomEvent<{ spaceId?: string }>;
      const sid = customEvt?.detail?.spaceId;
      if (!sid) return;
      setShowKnowledgeSquare(true);
      setSquarePreviewSpaceId(String(sid));
      setSquarePreviewSpace(null);
      setSquarePreviewDrawerOpen(true);
    };
    window.addEventListener(
      "knowledge-square-preview",
      onPreviewFromNotification as EventListener,
    );
    return () => {
      window.removeEventListener(
        "knowledge-square-preview",
        onPreviewFromNotification as EventListener,
      );
    };
  }, [
    setShowKnowledgeSquare,
    setSquarePreviewDrawerOpen,
    setSquarePreviewSpace,
    setSquarePreviewSpaceId,
  ]);

  // Share link guard: if /knowledge/share/:spaceId points to an invalid/private space,
  // or a space whose join policy changed (approval -> public), show toast and redirect to square.
  // Space creator opens their own share link → go to space detail (same as sidebar entry).
  useEffect(() => {
    if (!previewSpaceId) return;
    if (knowledgePluginGate === "loading" || knowledgePluginGate === "disabled")
      return;
    let cancelled = false;
    setPreviewDrawerOpen(false);
    (async () => {
      try {
        const info = await getSpaceInfoApi(previewSpaceId);
        if (cancelled) return;

        // Anyone who can already read the space goes straight into it —
        // a share link is a way in, not an application form. Only the
        // creator short-circuited here, so a member or a granted user
        // landed on the intro-and-apply drawer for a space that was
        // already sitting in their own sidebar. `visible` is the same
        // decision the space's own pages enforce; `role` cannot answer it,
        // because an absent role maps to MEMBER exactly like a real one.
        if (canOpenSharedSpace(info)) {
          navigateRef.current(`/knowledge/space/${previewSpaceId}`, {
            replace: true,
          });
          return;
        }

        // Frontend fallback: in some scenarios (e.g. creator share link),
        // `/info` may not provide `role/user_role`.
        // If the space exists in "mine created" list, treat as creator and go to detail page.
        try {
          const mineSpaces = await getMineSpacesApi();
          const previewId = String(previewSpaceId);
          const isMineCreator = mineSpaces.some(
            (s) => s.id === previewId && s.role === SpaceRole.CREATOR,
          );
          if (isMineCreator) {
            navigateRef.current(`/knowledge/space/${previewSpaceId}`, {
              replace: true,
            });
            return;
          }
        } catch {
          // ignore fallback error, keep existing guard behavior
        }

        // If the space is now private/inaccessible, treat as invalid for share links.
        if (info.visibility === VisibilityType.PRIVATE) {
          showToastRef.current({
            message: localizeRef.current(
              "com_knowledge.space_invalid_or_deleted",
            ),
            severity: NotificationSeverity.WARNING,
          });
          setPreviewDrawerOpen(false);
          navigateRef.current("/knowledge?square=1", { replace: true });
          return;
        }

        // Space changed from approval to public while user had a pending application.
        // Product expectation: toast + redirect to square page.
        if (info.visibility === VisibilityType.PUBLIC && info.isPending) {
          showToastRef.current({
            message: localizeRef.current(
              "com_knowledge.space_became_public_go_square",
            ),
            severity: NotificationSeverity.WARNING,
          });
          setPreviewDrawerOpen(false);
          navigateRef.current("/knowledge?square=1", { replace: true });
          return;
        }

        setPreviewDrawerOpen(true);
      } catch (error) {
        if (cancelled) return;
        // Same rule as the detail load: a share link only sends the user to
        // the square when the server says the space is gone or closed.
        const failure = resolveSpaceInfoFailure(error);
        showToastRef.current({
          message: failure.message || localizeRef.current(failure.messageKey),
          severity: NotificationSeverity.WARNING,
        });
        if (failure.leaveSpace) {
          setPreviewDrawerOpen(false);
          navigateRef.current("/knowledge?square=1", { replace: true });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    previewSpaceId,
    knowledgePluginGate,
    knowledgeTabActivateEpoch,
    localizeRef,
    navigateRef,
    setPreviewDrawerOpen,
    showToastRef,
  ]);
}
