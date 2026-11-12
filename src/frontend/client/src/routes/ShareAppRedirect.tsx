import { useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { NotificationSeverity } from '~/common';
import { Spinner } from '~/components/svg';
import { useLocalize } from '~/hooks';
import { useToastContext } from '~/Providers';
import { generateUUID } from '~/utils';

/**
 * Landing page for shared app links: /share/app/{applicationId}_{flowType}
 *
 * Parses the slug to extract applicationId and flowType,
 * then creates a new conversation and redirects to the app chat page.
 * Same behavior as clicking an app card in the app center.
 */
export default function ShareAppRedirect() {
  const { appSlug } = useParams<{ appSlug: string }>();
  const navigate = useNavigate();
  const { showToast } = useToastContext();
  const localize = useLocalize();

  useEffect(() => {
    if (!appSlug) {
      navigate('/apps', { replace: true });
      return;
    }

    // Parse slug: "{applicationId}_{flowType}"
    // flowType is the last segment after the last underscore
    const lastUnderscoreIdx = appSlug.lastIndexOf('_');
    if (lastUnderscoreIdx === -1) {
      showToast?.({ message: localize('com_app_invalid_share_link'), severity: NotificationSeverity.WARNING });
      navigate('/apps', { replace: true });
      return;
    }

    const applicationId = appSlug.substring(0, lastUnderscoreIdx);
    const flowType = appSlug.substring(lastUnderscoreIdx + 1);

    if (!applicationId || !flowType) {
      showToast?.({ message: localize('com_app_invalid_share_link'), severity: NotificationSeverity.WARNING });
      navigate('/apps', { replace: true });
      return;
    }

    // Create a new conversation and navigate — same as clicking a card
    const chatId = generateUUID(32);
    navigate(`/app/${chatId}/${applicationId}/${flowType}?from=share`, { replace: true });
  }, [appSlug, navigate, showToast, localize]);

  // Show loading spinner during redirect
  return (
    <div className="flex h-screen items-center justify-center">
      <Spinner className="text-blue-500" />
    </div>
  );
}
