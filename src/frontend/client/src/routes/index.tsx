import {
  ApiErrorWatcher,
  Login,
  TwoFactorScreen
} from '@/components/Auth';
import WebView from '@/components/WebView';
import { AuthContextProvider } from '@/hooks/AuthContext';
import AppChat from '@/pages/appChat';
import AppChatEntry from '@/pages/appChat/AppChatEntry';
import AgentCenter from '@/pages/apps';
import ExplorePlaza from '@/pages/apps/explore';
import Share from '@/pages/share';
import { createBrowserRouter, Navigate, Outlet, useParams } from 'react-router-dom';
import ChatRoute from './ChatRoute';
import LoginLayout from './Layouts/Login';
import RouteErrorBoundary from './RouteErrorBoundary';
// import ShareRoute from './ShareRoute';
import Sop from '@/components/Sop';
import MainLayout from '@/layouts/MainLayout';
import Page404 from '@/pages/Page404';
import Page403 from '@/pages/Page403';
import { AliveScope } from 'react-activation';
import Subscription from '~/pages/Subscription';
import AppRoot from './AppRoot';
import Root from './Root';
import Knowledge from '~/pages/knowledge';
import FilePreviewPage from '~/pages/knowledge/FilePreview/FilePreviewPage';
import DevLogin from '~/pages/DevLogin';
import StandaloneChatPage from '~/pages/standaloneChat/StandaloneChatPage';
import MenuUnavailablePage from '@/pages/MenuUnavailablePage';
import { useAuthContext } from '@/hooks';
import { appsSectionLinkTarget } from '@/layouts/appModuleNavPaths';
import { canOpenWorkbench } from '@/utils/platformAccess';

function HomeEntryRedirect() {
  const { user } = useAuthContext();
  const plugins = (user as { plugins?: string[] } | null)?.plugins;
  const approval = Boolean((user as { menu_approval_mode?: boolean } | null)?.menu_approval_mode);
  if (!Array.isArray(plugins)) {
    return <Navigate to="/c/new" replace />;
  }
  const canOpenWorkbenchEntry = canOpenWorkbench({
    role: user?.role,
    plugins,
    is_department_admin: (user as { is_department_admin?: boolean } | null)?.is_department_admin,
  });
  if (!canOpenWorkbenchEntry) {
    return <Navigate to="/404" replace />;
  }
  const has = (id: string) => plugins.includes(id);
  if (has('home') || approval) {
    return <Navigate to="/c/new" replace />;
  }
  if (has('apps')) {
    return <Navigate to={appsSectionLinkTarget()} replace />;
  }
  if (has('subscription')) {
    return <Navigate to="/channel" replace />;
  }
  if (has('knowledge_space')) {
    return <Navigate to="/knowledge" replace />;
  }
  return <Navigate to="/menu-unavailable" replace />;
}

const AuthLayout = () => (
  <AuthContextProvider>
    <AliveScope>
      <Outlet />
    </AliveScope>
    <ApiErrorWatcher />
  </AuthContextProvider>
);

export const LegacyRedirect = ({ toPattern }: { toPattern: (params: Record<string, string | undefined>) => string }) => {
  const params = useParams();
  return <Navigate to={toPattern(params)} replace />;
};

const baseConfig = {
  //@ts-ignore
  basename: __APP_ENV__.BASE_URL
}

export const router = createBrowserRouter([
  {
    element: <AuthLayout />,
    errorElement: <RouteErrorBoundary />,
    children: [
      {
        path: __APP_ENV__.BISHENG_HOST,
        element: <LoginLayout />,
        children: [
          { path: 'login', element: <Login /> },
          { path: 'login/2fa', element: <TwoFactorScreen /> },
        ],
      },
      {
        path: '/',
        element: <MainLayout />,
        children: [
          {
            path: '',
            element: <Root />,
            children: [
              { index: true, element: <HomeEntryRedirect /> },
              { path: 'c/:conversationId?', element: <ChatRoute /> },
              { path: 'linsight/:conversationId?', element: <Sop /> },
              { path: 'linsight/case/:sopId', element: <Sop /> },
              // { path: 'apps', element: <AgentCenter /> },
            ],
          },
          {
            path: 'app', element: <AppRoot />, children: [
              { path: ':fid/:type', element: <AppChatEntry /> },
              { path: ':conversationId/:fid/:type', element: <AppChat /> }
            ]
          },
          {
            // === 兼容旧路由 ===
            path: 'chat/:conversationId/:fid/:type',
            element: <LegacyRedirect toPattern={(p) => `/app/${p.conversationId}/${p.fid}/${p.type}`} />
          },
          { path: 'apps', element: <AgentCenter /> },
          { path: 'apps/explore', element: <ExplorePlaza /> },
          { path: 'channel', element: <Subscription /> },
          { path: 'channel/share/:channelId', element: <Subscription /> },
          { path: 'channel/:channelId', element: <Subscription /> },
          { path: 'knowledge', element: <Knowledge /> },
          { path: 'knowledge/space/:spaceId', element: <Knowledge /> },
          { path: 'knowledge/space/:spaceId/folder/:folderId', element: <Knowledge /> },
          { path: 'knowledge/share/:spaceId', element: <Knowledge /> },
          { path: 'menu-unavailable', element: <MenuUnavailablePage /> },
        ],
      },
      // Standalone chat — auth (login required, inside AuthLayout)
      { path: 'chat/flow/auth/:flowId', element: <StandaloneChatPage mode="auth" flowType="workflow" /> },
      { path: 'chat/assistant/auth/:flowId', element: <StandaloneChatPage mode="auth" flowType="assistant" /> },

      { path: 'share/:token/:vid?', element: <Share /> },
      { path: 'knowledge/file/:fileId', element: <FilePreviewPage /> },
    ],
  },
  // Standalone chat — guest (no login, outside AuthLayout to avoid 401 redirect)
  { path: 'chat/flow/:flowId', element: <StandaloneChatPage mode="guest" flowType="workflow" />, errorElement: <RouteErrorBoundary /> },
  { path: 'chat/assistant/:flowId', element: <StandaloneChatPage mode="guest" flowType="assistant" />, errorElement: <RouteErrorBoundary /> },
  { path: '/html', element: <WebView /> },
  { path: '/__dev/login', element: <DevLogin /> },
  { path: '/404', element: <Page404 /> },
  { path: '/403', element: <Page403 /> },
  { path: "*", element: <Navigate to="/404" replace /> }
], baseConfig);
