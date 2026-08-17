import { ErrorPage, collectDiagnostics } from '@bisheng/ui';
import { useContext, useMemo } from 'react';
import { useRouteError } from 'react-router-dom';
import { SystemErrorIllustration } from '~/components/illustrations';
import { AuthContext } from '~/hooks/AuthContext';
import { useToastContext } from '~/Providers';
import { useLocalize } from '~/hooks';

/**
 * Crash screen for anything the router throws.
 *
 * The screen itself lives in @bisheng/ui so this app and the admin app hand a
 * support engineer the same identifiers, the same QR payload and the same log
 * file — an engineer reading a user's screenshot should not have to know which
 * app it came from. Everything app-shaped stays here: where the error comes
 * from, who was signed in, and the translations.
 */
export default function RouteErrorBoundary() {
  const error = useRouteError() as {
    message?: string;
    stack?: string;
    status?: number;
    statusText?: string;
  };
  const localize = useLocalize();
  // Read straight off the context rather than through useAuthContext, which
  // throws when the provider is missing — and it is missing here: an
  // errorElement renders *in place of* its route's element, so this screen
  // lives outside the layout that provides it. A crash screen that can itself
  // crash leaves the user with a white page and nothing to report.
  const auth = useContext(AuthContext);
  // The toast provider and its viewport both sit outside the router, so they
  // survive the crash that put this screen on screen.
  const { showToast } = useToastContext();

  // Collected once: the trace id names this occurrence, and a re-render must not
  // rename it after the user has already screenshotted it.
  const diagnostics = useMemo(
    () =>
      collectDiagnostics({
        error: error ?? {},
        // Guarded for the same reason: the define is absent if the page is
        // opened from a bundle built before it existed.
        version: typeof __APP_VERSION__ === 'string' ? __APP_VERSION__ : 'unknown',
        user: auth?.user?.username,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deliberately once per mount
    [],
  );

  return (
    <ErrorPage
      diagnostics={diagnostics}
      illustration={<SystemErrorIllustration className="size-[120px]" />}
      onCopied={() => showToast({ message: localize('com_ui_copied_to_clipboard'), status: 'success' })}
      labels={{
        title: localize('com_error_page.title'),
        description: localize('com_error_page.description'),
        copyBefore: localize('com_error_page.copy_before'),
        copyLink: localize('com_error_page.copy_link'),
        copyAfter: localize('com_error_page.copy_after'),
        refresh: localize('com_error_page.refresh'),
        download: localize('com_error_page.download'),
        screenshotHint: localize('com_error_page.screenshot_hint'),
        traceId: localize('com_error_page.trace_id'),
        errorCode: localize('com_error_page.error_code'),
        time: localize('com_error_page.time'),
        version: localize('com_error_page.version'),
        route: localize('com_error_page.route'),
        user: localize('com_error_page.user'),
      }}
    />
  );
}
