import { ErrorBoundary } from "react-error-boundary";
import { Navigate, createBrowserRouter } from "react-router-dom";
import CrashErrorComponent from "./components/CrashErrorComponent";
import MainLayout from "./layout/MainLayout";
import SkillChatPage from "./pages/ChatAppPage";
import ChatAssitantShare from "./pages/ChatAppPage/chatAssitantShare";
import AssistantChat from "./pages/ChatAppPage/chatPage/AssistantChatPage";
import SkillChat from "./pages/ChatAppPage/chatPage/SkillChatPage";
import ChatShare from "./pages/ChatAppPage/chatShare";
import ChatPro from "./pages/ChatAppPage/chatWebview";
import DiffFlowPage from "./pages/DiffFlowPage";
import EvaluatingPage from "./pages/EvaluationPage";
import EvaluatingCreate from "./pages/EvaluationPage/EvaluationCreate";
import FileLibPage from "./pages/FileLibPage";
import FilesPage from "./pages/FileLibPage/detail";
import FlowPage from "./pages/FlowPage";
import LogPage from "./pages/LogPage";
import { LoginPage } from "./pages/LoginPage/login";
import { ResetPwdPage } from "./pages/LoginPage/resetPwd";
import Doc from "./pages/ModelPage/doc";
import { Finetune } from "./pages/ModelPage/finetune";
import Management from "./pages/ModelPage/manage";
import Page403 from "./pages/Page403";
import Report from "./pages/Report";
import EditAssistantPage from "./pages/SkillPage/editAssistant";
import L2Edit from "./pages/SkillPage/l2Edit";
import SkillAssisPage from "./pages/SkillPage/tabAssistant";
import SkillsPage from "./pages/SkillPage/tabSkills";
import SkillToolsPage from "./pages/SkillPage/tabTools";
import Templates from "./pages/SkillPage/temps";
import SystemPage from "./pages/SystemPage";
import FilesUpload from "./pages/FileLibPage/filesUpload";

// react 与 react router dom版本不匹配
// const FileLibPage = lazy(() => import(/* webpackChunkName: "FileLibPage" */ "./pages/FileLibPage"));
// const FilesPage = lazy(() => import(/* webpackChunkName: "FilesPage" */ "./pages/FileLibPage/files"));
// const SkillPage = lazy(() => import(/* webpackChunkName: "SkillPage" */ "./pages/SkillPage"));
// const SkillChatPage = lazy(() => import(/* webpackChunkName: "SkillChatPage" */ "./pages/SkillChatPage"));

const ErrorHoc = ({ Comp }) => {
  return (
    <ErrorBoundary
      onReset={() => window.location.href = window.location.href}
      FallbackComponent={CrashErrorComponent}
    >
      <Comp />
    </ErrorBoundary>
  );
}

const baseConfig = {
  //@ts-ignore
  basename: __APP_ENV__.BASE_URL
}


const privateRouter = [
  {
    path: "/",
    element: <MainLayout />,
    children: [
      { path: "", element: <SkillChatPage />, },
      { path: "filelib", element: <FileLibPage />, permission: 'knowledge', },
      { path: "filelib/:id", element: <FilesPage />, permission: 'knowledge', },
      { path: "filelib/upload/:id", element: <FilesUpload />, permission: 'knowledge', },
      { path: "build/assist", element: <SkillAssisPage />, permission: 'build', },
      { path: "build/skills", element: <SkillsPage />, permission: 'build', },
      // @ts-ignore
      { path: "build/tools", element: <SkillToolsPage />, permission: 'build', },
      { path: "build", element: <Navigate to="assist" replace /> },
      { path: "build/skill", element: <L2Edit />, permission: 'build', },
      { path: "build/skill/:id/:vid", element: <L2Edit />, permission: 'build', },
      { path: "build/temps", element: <Templates />, permission: 'build', },
      { path: "model/management", element: <Management /> },
      { path: "model/finetune", element: <Finetune /> },
      { path: "model", element: <Navigate to="management" replace /> },
      { path: "sys", element: <SystemPage />, permission: 'sys' },
      { path: "log", element: <LogPage /> },
      { path: "evaluation", element: <EvaluatingPage /> },
      { path: "evaluation/create", element: <EvaluatingCreate /> },

    ],
  },
  { path: "model/doc", element: <Doc /> },
  {
    path: "/flow/:id/",
    children: [
      { path: "", element: <ErrorHoc Comp={FlowPage} /> }
    ]
  },
  {
    path: "/assistant/:id/",
    children: [
      { path: "", element: <EditAssistantPage /> }
    ]
  },
  // 独立会话页
  { path: "/chat/assistant/auth/:id/", element: <ChatPro type='assistant' /> },
  { path: "/chat/skill/auth/:id/", element: <ChatPro /> },
  { path: "/chat", element: <SkillChatPage /> },
  { path: "/chat/:id/", element: <ChatShare /> },
  { path: "/chat/assistant/:id/", element: <ChatAssitantShare /> },
  { path: "/report/:id/", element: <Report /> },
  { path: "/diff/:id/:vid/:cid", element: <ErrorHoc Comp={DiffFlowPage} /> },
  { path: "/reset", element: <ResetPwdPage /> },
  { path: "/403", element: <Page403 /> },
  { path: "*", element: <Navigate to="/" replace /> }
]

export const getPrivateRouter = (permissions) => {
  const filterMenuItem = (_privateRouter) => {
    const result = _privateRouter.reduce((res, cur) => {
      // 递归
      if (cur.children?.length) {
        cur.children = filterMenuItem(cur.children)
      }

      const { permission, ...other } = cur
      if (permission && !permissions.includes(permission)) {
        return res
      }

      res.push(other)
      return res
    }, [])

    return result
  }

  return createBrowserRouter(permissions ? filterMenuItem(privateRouter) : [],
    baseConfig)
}

export const getAdminRouter = () => {
  return createBrowserRouter(privateRouter,
    baseConfig)
}

export const publicRouter = createBrowserRouter([
  { path: "/", element: <LoginPage /> },
  { path: "/reset", element: <ResetPwdPage /> },
  { path: "/chat/:id/", element: <ChatShare /> },
  { path: "/chat/assistant/:id/", element: <ChatAssitantShare /> },
  { path: "/403", element: <Page403 /> },
  { path: "*", element: <LoginPage /> }
],
  baseConfig)
