import { ErrorBoundary } from "react-error-boundary";
import { Navigate, createBrowserRouter } from "react-router-dom";
import CrashErrorComponent from "./components/CrashErrorComponent";
import MainLayout from "./layout/MainLayout";
import Templates from "./pages/BuildPage/appTemps";
import Apps from "./pages/BuildPage/apps";
import SkillAssisPage from "./pages/BuildPage/assistant";
import EditAssistantPage from "./pages/BuildPage/assistant/editAssistant";
import FlowPage from "./pages/BuildPage/flow";
import SkillsPage from "./pages/BuildPage/skills";
import SkillPage from "./pages/BuildPage/skills/editSkill";
import L2Edit from "./pages/BuildPage/skills/l2Edit";
import SkillToolsPage from "./pages/BuildPage/tools";
import SkillChatPage from "./pages/ChatAppPage";
import ChatAssitantShare from "./pages/ChatAppPage/chatAssitantShare";
import ChatShare from "./pages/ChatAppPage/chatShare";
import ChatPro from "./pages/ChatAppPage/chatWebview";
import DataSetPage from "./pages/DataSetPage";
import DiffFlowPage from "./pages/DiffFlowPage";
import EvaluatingPage from "./pages/EvaluationPage";
import EvaluatingCreate from "./pages/EvaluationPage/EvaluationCreate";
import KnowledgePage from "./pages/KnowledgePage";
import FilesPage from "./pages/KnowledgePage/detail";
import FilesUpload from "./pages/KnowledgePage/filesUpload";
import QasPage from "./pages/KnowledgePage/qas";
import LabelPage from "./pages/LabelPage";
import TaskAppChats from "./pages/LabelPage/taskAppChats";
import TaskApps from "./pages/LabelPage/taskApps";
import LogPage from "./pages/LogPage";
import AppChatDetail from "./pages/LogPage/useAppLog/appChatDetail";
import { LoginPage } from "./pages/LoginPage/login";
import { ResetPwdPage } from "./pages/LoginPage/resetPwd";
import Doc from "./pages/ModelPage/doc";
import { Finetune } from "./pages/ModelPage/finetune";
import Management from "./pages/ModelPage/manage";
import Page403 from "./pages/Page403";
import Report from "./pages/Report";
import SystemPage from "./pages/SystemPage";
import ResoucePage from "./pages/resoucePage";

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
      { path: "filelib", element: <KnowledgePage />, permission: 'knowledge', },
      { path: "filelib/:id", element: <FilesPage />, permission: 'knowledge', },
      { path: "filelib/upload/:id", element: <FilesUpload />, permission: 'knowledge', },
      { path: "filelib/qalib/:id", element: <QasPage />, permission: 'knowledge', },
      { path: "build/apps", element: <Apps />, permission: 'build', },
      // { path: "build/assist", element: <SkillAssisPage />, permission: 'build', },
      // { path: "build/skills", element: <SkillsPage />, permission: 'build', },
      // @ts-ignore
      { path: "build/tools", element: <SkillToolsPage />, permission: 'build', },
      { path: "build", element: <Navigate to="apps" replace /> },
      { path: "build/skill", element: <L2Edit />, permission: 'build', },
      { path: "build/skill/:id/:vid", element: <L2Edit />, permission: 'build', },
      { path: "build/temps/:type", element: <Templates />, permission: 'build', },
      { path: "model/management", element: <Management /> },
      { path: "model/finetune", element: <Finetune /> },
      { path: "model", element: <Navigate to="management" replace /> },
      { path: "sys", element: <SystemPage />, permission: 'sys' },
      { path: "log", element: <LogPage /> },
      { path: "log/chatlog/:fid/:cid/:type", element: <AppChatDetail /> },
      { path: "evaluation", element: <EvaluatingPage /> },
      { path: "evaluation/create", element: <EvaluatingCreate /> },
      { path: "dataset", element: <DataSetPage /> },
      { path: "label", element: <LabelPage /> },
      { path: "label/:id", element: <TaskApps /> },
      { path: "label/chat/:id/:fid/:cid/:type", element: <TaskAppChats /> },
    ],
  },
  { path: "model/doc", element: <Doc /> },
  {
    path: "/skill/:id/",
    children: [
      { path: "", element: <ErrorHoc Comp={SkillPage} /> }
    ]
  },
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
  {
    path: "/resouce/:cid/:mid",
    element: <ResoucePage />
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
  { path: "/resouce/:cid/:mid", element: <ResoucePage /> },
  { path: "/403", element: <Page403 /> },
  { path: "*", element: <LoginPage /> }
],
  baseConfig)
