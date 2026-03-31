import {
  ApiErrorWatcher,
  Login,
  TwoFactorScreen
} from '@/components/Auth';
import WebView from '@/components/WebView';
import { AuthContextProvider } from '@/hooks/AuthContext';
import AppChat from '@/pages/appChat';
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
import { AliveScope } from 'react-activation';
import Subscription from '~/pages/Subscription';
import AppRoot from './AppRoot';
import Root from './Root';
import Knowledge from '~/pages/knowledge';
import FilePreviewPage from '~/pages/knowledge/FilePreview/FilePreviewPage';

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
              { index: true, element: <Navigate to="/c/new" replace /> },
              { path: 'c/:conversationId?', element: <ChatRoute /> },
              { path: 'linsight/:conversationId?', element: <Sop /> },
              { path: 'linsight/case/:sopId', element: <Sop /> },
              // { path: 'apps', element: <AgentCenter /> },
            ],
          },
          {
            path: 'app', element: <AppRoot />, children: [
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
          { path: 'knowledge', element: <Knowledge /> },
          { path: 'knowledge/space/:spaceId', element: <Knowledge /> },
          { path: 'knowledge/space/:spaceId/folder/:folderId', element: <Knowledge /> },
          { path: 'knowledge/share/:spaceId', element: <Knowledge /> },
        ],
      },
      { path: 'share/:token/:vid?', element: <Share /> },
      { path: 'knowledge/file/:fileId', element: <FilePreviewPage /> },
    ],
  },
  { path: '/html', element: <WebView /> },
  { path: '/404', element: <Page404 /> },
  { path: "*", element: <Navigate to="/404" replace /> }
], baseConfig);