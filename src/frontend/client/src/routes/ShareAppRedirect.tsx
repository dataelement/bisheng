import { useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { NotificationSeverity } from '~/common';
import { Spinner } from '~/components/svg';
import { useToastContext } from '~/Providers';
import { getChatOnlineApi } from '~/api/apps';
import { generateUUID } from '~/utils';

/**
 * Landing page for shared app links: /share/app_{applicationId}
 *
 * Flow:
 * 1. User is already authenticated (wrapped in AuthContextProvider)
 * 2. Fetch app info to verify access
 * 3. If permission denied → redirect to /apps with error toast
 * 4. If has last conversation → navigate to it
 * 5. If no history → create new conversation and navigate
 */
export default function ShareAppRedirect() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const navigate = useNavigate();
  const { showToast } = useToastContext();

  useEffect(() => {
    if (!applicationId) {
      navigate('/apps', { replace: true });
      return;
    }

    const resolveApp = async () => {
      try {
        // Fetch app info to check access permission
        // eslint-disable-next-line @typescript-eslint/no-explicit-any -- API untyped
        const res: any = await getChatOnlineApi(1, '', -1, 200);
        const apps = res.data || [];
        // eslint-disable-next-line @typescript-eslint/no-explicit-any -- API untyped
        const targetApp = apps.find((app: any) => String(app.id) === applicationId);

        if (!targetApp) {
          showToast?.({ message: '无访问权限，请联系管理员', severity: NotificationSeverity.ERROR });
          navigate('/apps', { replace: true });
          return;
        }

        // Navigate to the app
        if (targetApp.last_chat_id) {
          navigate(
            `/app/${targetApp.last_chat_id}/${targetApp.id}/${targetApp.flow_type}`,
            { replace: true },
          );
        } else {
          const chatId = generateUUID(32);
          navigate(
            `/app/${chatId}/${targetApp.id}/${targetApp.flow_type}`,
            { replace: true },
          );
        }
      } catch {
        showToast?.({ message: '加载失败，请重试', severity: NotificationSeverity.ERROR });
        navigate('/apps', { replace: true });
      }
    };

    resolveApp();
  }, [applicationId, navigate, showToast]);

  // Show loading spinner during API requests
  return (
    <div className="flex h-screen items-center justify-center">
      <Spinner className="text-blue-500" />
    </div>
  );
}
