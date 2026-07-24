import {
  ApiErrorWatcher,
  Login,
  TwoFactorScreen
} from '@/components/Auth';
import { AuthContextProvider } from '@/hooks/AuthContext';
import { lazy, Suspense, type ReactNode } from 'react';
import { createBrowserRouter, Navigate, Outlet, useParams } from 'react-router-dom';
import ChatRoute from './ChatRoute';
import LoginLayout from './Layouts/Login';
import RouteErrorBoundary from './RouteErrorBoundary';
// import ShareRoute from './ShareRoute';
import MainLayout from '@/layouts/MainLayout';
import Page404 from '@/pages/Page404';
import Page403 from '@/pages/Page403';
import { AliveScope } from 'react-activation';
import AppRoot from './AppRoot';
import Root from './Root';
import MenuUnavailablePage from '@/pages/MenuUnavailablePage';
import { useAuthContext } from '@/hooks';
import MenuApprovalPluginGate from '@/layouts/MenuApprovalPluginGate';
import { appsSectionLinkTarget } from '@/layouts/appModuleNavPaths';
import { canOpenWorkbench } from '@/utils/platformAccess';
import { LoadingIcon } from '~/components/ui/icon/Loading';

// Route-level code splitting (ledger #27): only the primary landing path
// (login + main layout + chat home) ships in the entry chunk; every other
// page loads on first navigation.
const WebView = lazy(() => import('@/components/WebView'));
const AppChat = lazy(() => import('@/pages/appChat'));
const AppChatEntry = lazy(() => import('@/pages/appChat/AppChatEntry'));
const AgentCenter = lazy(() => import('@/pages/apps'));
const ExplorePlaza = lazy(() => import('@/pages/apps/explore'));
const Share = lazy(() => import('@/pages/share'));
const Sop = lazy(() => import('@/components/Sop'));
const Subscription = lazy(() => import('~/pages/Subscription'));
const Knowledge = lazy(() => import('~/pages/knowledge'));
const FilePreviewPage = lazy(() => import('~/pages/knowledge/FilePreview/FilePreviewPage'));
const ArticlePage = lazy(() => import('~/pages/Subscription/Article/ArticlePage'));
const DevLogin = lazy(() => import('~/pages/DevLogin'));
const StandaloneChatPage = lazy(() => import('~/pages/standaloneChat/StandaloneChatPage'));

function RouteLoading() {
  return (
    <div className="flex h-full min-h-[50vh] w-full items-center justify-center">
      <LoadingIcon className="size-16 text-blue-500" />
    </div>
  );
}

const suspended = (node: ReactNode) => <Suspense fallback={<RouteLoading />}>{node}</Suspense>;

function HomeEntryRedirect() {
  const { user } = useAuthContext();
  const plugins = (user as { plugins?: string[] } | null)?.plugins;
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
  // Only users with WEB_MENU `home` land on chat home; do not use menu_approval_mode here — it incorrectly
  // forced /c/new for every user when approval was on (same class of bug as apps center).
  if (has('home')) {
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
  // In approval mode, a new user may have workbench entry but no nav plugins yet.
  // Send them to the default apply page so they can request access instead of seeing
  // a dead-end generic message.
  // Workspace landing fallback uses the workbench approval scope (legacy flag as fallback).
  const menuApprovalMode = Boolean(
    (user as { menu_approval_mode_workbench?: boolean; menu_approval_mode?: boolean } | null)
      ?.menu_approval_mode_workbench
    ?? (user as { menu_approval_mode?: boolean } | null)?.menu_approval_mode,
  );
  if (menuApprovalMode) {
    return <Navigate to="/menu-unavailable?plugin=home" replace />;
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

// DEV-ONLY component gallery for the UI unification effort (docs-ui-refactor/).
// `import.meta.env.DEV` is statically false in production builds, so both the lazy
// import and the route below are tree-shaken out — the gallery never ships to users.
const GalleryApp = import.meta.env.DEV
  ? lazy(() => import('~/pages/_gallery/GalleryApp'))
  : null;

const devGalleryRoutes = import.meta.env.DEV && GalleryApp
  ? [{
      path: '/gallery',
      element: (
        <Suspense fallback={null}>
          <GalleryApp />
        </Suspense>
      ),
    }]
  : [];

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
              {
                path: 'c/:conversationId?',
                element: (
                  <MenuApprovalPluginGate pluginId="home">
                    <ChatRoute />
                  </MenuApprovalPluginGate>
                ),
              },
              {
                path: 'linsight/:conversationId?',
                element: suspended(
                  // F035: task mode has its own menu permission key, split from `home`
                  <MenuApprovalPluginGate pluginId="linsight_task_mode">
                    <Sop />
                  </MenuApprovalPluginGate>
                ),
              },
              {
                path: 'linsight/case/:sopId',
                element: suspended(
                  <MenuApprovalPluginGate pluginId="linsight_task_mode">
                    <Sop />
                  </MenuApprovalPluginGate>
                ),
              },
              // { path: 'apps', element: <AgentCenter /> },
            ],
          },
          {
            path: 'app', element: <AppRoot />, children: [
              { path: ':fid/:type', element: suspended(<AppChatEntry />) },
              { path: ':conversationId/:fid/:type', element: suspended(<AppChat />) }
            ]
          },
          {
            // === 兼容旧路由 ===
            path: 'chat/:conversationId/:fid/:type',
            element: <LegacyRedirect toPattern={(p) => `/app/${p.conversationId}/${p.fid}/${p.type}`} />
          },
          {
            path: 'apps',
            element: suspended(
              <MenuApprovalPluginGate pluginId="apps">
                <AgentCenter />
              </MenuApprovalPluginGate>
            ),
          },
          {
            path: 'apps/explore',
            element: suspended(
              <MenuApprovalPluginGate pluginId="apps">
                <ExplorePlaza />
              </MenuApprovalPluginGate>
            ),
          },
          { path: 'channel', element: suspended(
            <MenuApprovalPluginGate pluginId="subscription">
              <Subscription />
            </MenuApprovalPluginGate>
          )},
          { path: 'channel/share/:channelId', element: suspended(<Subscription />) },
          { path: 'channel/:channelId', element: suspended(
            <MenuApprovalPluginGate pluginId="subscription">
              <Subscription />
            </MenuApprovalPluginGate>
          )},
          { path: 'knowledge', element: suspended(
            <MenuApprovalPluginGate pluginId="knowledge_space">
              <Knowledge />
            </MenuApprovalPluginGate>
          )},
          { path: 'knowledge/space/:spaceId', element: suspended(
            <MenuApprovalPluginGate pluginId="knowledge_space">
              <Knowledge />
            </MenuApprovalPluginGate>
          )},
          { path: 'knowledge/space/:spaceId/folder/:folderId', element: suspended(
            <MenuApprovalPluginGate pluginId="knowledge_space">
              <Knowledge />
            </MenuApprovalPluginGate>
          )},
          { path: 'knowledge/share/:spaceId', element: suspended(<Knowledge />) },
          { path: 'menu-unavailable', element: <MenuUnavailablePage /> },
        ],
      },
      // Standalone chat — auth (login required, inside AuthLayout)
      { path: 'chat/flow/auth/:flowId', element: suspended(<StandaloneChatPage mode="auth" flowType="workflow" />) },
      { path: 'chat/assistant/auth/:flowId', element: suspended(<StandaloneChatPage mode="auth" flowType="assistant" />) },

      { path: 'share/:token/:vid?', element: suspended(<Share />) },
      { path: 'knowledge/file/:fileId', element: suspended(<FilePreviewPage />) },
      { path: 'channel/:channelId/article/:articleId', element: suspended(<ArticlePage />) },
    ],
  },
  // Standalone chat — guest (no login, outside AuthLayout to avoid 401 redirect)
  { path: 'chat/flow/:flowId', element: suspended(<StandaloneChatPage mode="guest" flowType="workflow" />), errorElement: <RouteErrorBoundary /> },
  { path: 'chat/assistant/:flowId', element: suspended(<StandaloneChatPage mode="guest" flowType="assistant" />), errorElement: <RouteErrorBoundary /> },
  { path: '/html', element: suspended(<WebView />) },
  ...devGalleryRoutes,
  { path: '/__dev/login', element: suspended(<DevLogin />) },
  { path: '/404', element: <Page404 /> },
  { path: '/403', element: <Page403 /> },
  { path: "*", element: <Navigate to="/404" replace /> }
], baseConfig);
