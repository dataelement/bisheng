/**
 * Read the share token off the CURRENT ROUTE (`/share/:token/:vid?`).
 *
 * Every endpoint behind a share link authorizes on a `share-token` request
 * header, so a share recipient (neither owner nor admin) 403s without it —
 * which the global interceptor turns into a whole-page bounce to
 * `/c/new?error=11403`.
 *
 * WHY LOCATION AND NOT A PROP: the artifact helpers that need the token
 * (`resolveArtifactUrl` and friends in `~/components/Linsight/Artifacts/
 * artifactUtils.ts`) are plain modules, not components — they cannot call
 * `useParams`, and their four call sites sit five component layers below the
 * share route (ExecutionFlow / WorkspacePanel / FilePreviewPanel / PreviewBody /
 * SaveAsButton). Drilling a `shareToken` prop through all of them is churn that
 * the next call site would silently skip again — exactly how `file_download`
 * came to be the one linsight endpoint missing the header. Deriving it from the
 * route keeps a single source of truth. `TaskTurnPanel` already reads the token
 * straight off the route for the same reason.
 *
 * Callers that run OUTSIDE the share route — the standalone `/html` artifact
 * viewer tab, which is `window.open`ed and so has its own location — must pass
 * the token explicitly instead.
 */
export function getShareTokenFromPath(pathname: string = window.location.pathname): string {
  const base = (__APP_ENV__.BASE_URL || '').replace(/\/$/, '');
  const rest = base && pathname.startsWith(base) ? pathname.slice(base.length) : pathname;
  const matched = /^\/share\/([^/]+)/.exec(rest);
  if (!matched) {
    return '';
  }
  try {
    return decodeURIComponent(matched[1]);
  } catch {
    // A token that isn't valid percent-encoding is still a usable opaque string.
    return matched[1];
  }
}
