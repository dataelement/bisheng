import { createBrowserRouter, Navigate, Outlet } from 'react-router-dom';
import {
  ApiErrorWatcher,
  Login,
  Registration,
  RequestPasswordReset,
  ResetPassword,
  TwoFactorScreen,
  VerifyEmail,
} from '~/components/Auth';
import Sop from '~/components/Sop';
import WebView from '~/components/WebView';
import { AuthContextProvider } from '~/hooks/AuthContext';
import AppChat from '~/pages/appChat';
import AgentCenter from '~/pages/apps';
import Share from '~/pages/share';
import ChatRoute from './ChatRoute';
import LoginLayout from './Layouts/Login';
import StartupLayout from './Layouts/Startup';
import Root from './Root';
import RouteErrorBoundary from './RouteErrorBoundary';
// import ShareRoute from './ShareRoute';
import Page404 from '~/pages/Page404';

const AuthLayout = () => (
  <AuthContextProvider>
    <Outlet />
    <ApiErrorWatcher />
  </AuthContextProvider>
);

const baseConfig = {
  //@ts-ignore
  basename: __APP_ENV__.BASE_URL
}

export const router = createBrowserRouter([
  // {
  //   path: 'share/:shareId',
  //   element: <ShareRoute />,
  //   errorElement: <RouteErrorBoundary />,
  // },
  {
    path: '/',
    element: <StartupLayout />,
    errorElement: <RouteErrorBoundary />,
    children: [
      {
        path: 'register',
        element: <Registration />,
      },
      {
        path: 'forgot-password',
        element: <RequestPasswordReset />,
      },
      {
        path: 'reset-password',
        element: <ResetPassword />,
      },
    ],
  },
  {
    path: 'verify',
    element: <VerifyEmail />,
    errorElement: <RouteErrorBoundary />,
  },
  {
    element: <AuthLayout />,
    errorElement: <RouteErrorBoundary />,
    children: [
      {
        path: '/' + __APP_ENV__.BISHENG_HOST,
        element: <LoginLayout />,
        children: [
          {
            path: 'login',
            element: <Login />,
          },
          {
            path: 'login/2fa',
            element: <TwoFactorScreen />,
          },
        ],
      },
      // 提示词管理
      // dashboardRoutes,
      {
        path: '/',
        element: <Root />, // 包含会话列表
        children: [
          {
            index: true,
            element: <Navigate to="/c/new?" replace={true} />,
          },
          {
            path: 'c/:conversationId?',
            element: <ChatRoute />,
          },
          {
            path: 'linsight/:conversationId?',
            element: <Sop />,
          },
          {
            path: 'linsight/case/:sopId',
            element: <Sop />,
          },
          {
            path: 'apps',
            element: <AgentCenter />,
          },
          {
            path: 'chat/:conversationId/:fid/:type',
            element: <AppChat />,
          },
          {
            path: 'share/:token',
            element: <Share />,
          },
          {
            path: 'share/:token/:vid',
            element: <Share />,
          },
        ],
      },
    ],
  },
  {
    path: '/html',
    element: <WebView />,
  },
  {
    path: '/404',
    element: <Page404 />,
    errorElement: <RouteErrorBoundary />,
  },
  { path: "*", element: <Navigate to="/404" replace /> }
], baseConfig);
