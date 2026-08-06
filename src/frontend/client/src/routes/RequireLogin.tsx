import { ReactNode, useEffect, useState } from 'react';
import { LoginHandoff } from '~/components/Auth';
import { LoadingIcon } from '~/components/ui/icon/Loading';
import { useAuthContext } from '~/hooks';
import { buildReturnTo, redirectToLogin } from '~/utils/loginRedirect';

/**
 * One-shot marker recording that we already sent this exact URL to the login
 * page in this tab. If we are back here and STILL not authenticated, looping is
 * pointless — hand control to the user instead.
 */
const HANDOFF_KEY = 'bs:login-handoff';

function readHandoffMark(): string | null {
  try {
    return sessionStorage.getItem(HANDOFF_KEY);
  } catch {
    return null;
  }
}

function writeHandoffMark(value: string | null): void {
  try {
    if (value === null) {
      sessionStorage.removeItem(HANDOFF_KEY);
    } else {
      sessionStorage.setItem(HANDOFF_KEY, value);
    }
  } catch {
    /* private mode / storage disabled — we just lose the loop guard */
  }
}

/**
 * Gate a route behind login.
 *
 * Applied to the share route, which hangs directly off `AuthLayout` — it never
 * passes through `MainLayout`/`Root`, so nothing used to stop it from mounting
 * its content components while unauthenticated. The result was a page that
 * rendered an empty `ChatView` (header title "New Chat") on top of a burst of
 * doomed 401s: /workstation/config, /workstation/messages/{id}/agent,
 * /linsight/workbench/session-version-list. Every one of those endpoints is
 * `LoginUserDep`-gated, so the share-token check inside them is unreachable
 * without a session.
 *
 * The redirect here is NOT gated on `import.meta.env.MODE` (unlike the global
 * 401 interceptor in `~/api/request.ts`): a blank share page is never a useful
 * dev affordance, and the login target is resolved through
 * `getPlatformAdminPanelUrl()`, which handles the dev origin split.
 */
export function RequireLogin({ children }: { children: ReactNode }) {
  const { isAuthenticated, isUserLoading, user } = useAuthContext();
  const [blocked, setBlocked] = useState(false);
  const returnTo = buildReturnTo();

  // `isAuthenticated` is React state assigned from an effect, so it trails the
  // Recoil `user` by one render: there is a frame where `isUserLoading` is
  // already false, `user` is populated, and `isAuthenticated` is still false.
  // `Root.tsx` survives that frame because it merely renders null; a redirect
  // cannot — it fired on a perfectly valid session and bounced signed-in users
  // to the login page. A `user` object only exists after /user/info succeeded,
  // so it is the earlier, equally trustworthy signal.
  const authed = isAuthenticated || Boolean(user);

  useEffect(() => {
    if (isUserLoading) {
      return;
    }
    if (authed) {
      writeHandoffMark(null);
      setBlocked(false);
      return;
    }
    if (readHandoffMark() === returnTo) {
      // Already made the round trip for this URL and came back anonymous.
      setBlocked(true);
      return;
    }
    writeHandoffMark(returnTo);
    redirectToLogin(returnTo);
  }, [authed, isUserLoading, returnTo]);

  const handleLogin = () => {
    // A user-initiated attempt gets a clean slate: clear the loop marker and
    // force the navigation past the concurrent-401 dedupe guard.
    writeHandoffMark(returnTo);
    redirectToLogin(returnTo, { force: true });
  };

  if (isUserLoading) {
    // Same startup spinner as `routes/Root.tsx`, so the platform → client
    // hand-off shows no size or position jump, and so the handoff card does not
    // flash for the (common) already-authenticated visitor.
    return (
      <div className="flex h-[100dvh] w-full items-center justify-center bg-background">
        <LoadingIcon className="w-48 text-primary" />
      </div>
    );
  }

  if (!authed) {
    return <LoginHandoff state={blocked ? 'blocked' : 'pending'} onLogin={handleLogin} />;
  }

  return <>{children}</>;
}
