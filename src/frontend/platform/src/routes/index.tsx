import { lazy, useEffect } from "react";
import { Navigate, createBrowserRouter } from "react-router-dom";
import MainLayout from "../layout/MainLayout";
import { LoginPage } from "../pages/LoginPage/login";
import { ResetPwdPage } from "../pages/LoginPage/resetPwd";
import Page403 from "../pages/Page403";
import Page404 from "../pages/Page404";
import { AppNumType } from "../types/app";
import RouteErrorBoundary from "./RouteErrorBoundary";
import EditorPage from "@/pages/Dashboard/editor";

// 异步加载页面组件
const Templates = lazy(() => import("@/pages/BuildPage/appTemps"));
const Apps = lazy(() => import("@/pages/BuildPage/apps"));
const EditAssistantPage = lazy(() => import("@/pages/BuildPage/assistant/editAssistant"));
const WorkBenchPage = lazy(() => import("@/pages/BuildPage/bench/DialogueWork"));
const FlowPage = lazy(() => import("@/pages/BuildPage/flow"));
const SkillPage = lazy(() => import("@/pages/BuildPage/skills/editSkill"));
const L2Edit = lazy(() => import("@/pages/BuildPage/skills/l2Edit"));
const SkillToolsPage = lazy(() => import("@/pages/BuildPage/tools"));
const SkillChatPage = lazy(() => import("@/pages/ChatAppPage"));
const ChatAssitantShare = lazy(() => import("@/pages/ChatAppPage/chatAssitantShare"));
const ChatShare = lazy(() => import("@/pages/ChatAppPage/chatShare"));
const ChatPro = lazy(() => import("@/pages/ChatAppPage/chatWebview"));
const DataSetPage = lazy(() => import("@/pages/DataSetPage"));
const DiffFlowPage = lazy(() => import("@/pages/DiffFlowPage"));
const EvaluatingPage = lazy(() => import("@/pages/EvaluationPage"));
const EvaluatingCreate = lazy(() => import("@/pages/EvaluationPage/EvaluationCreate"));
const KnowledgePage = lazy(() => import("@/pages/KnowledgePage"));
const AdjustFilesUpload = lazy(() => import("@/pages/KnowledgePage/AdjustFilesUpload"));
const FilesPage = lazy(() => import("@/pages/KnowledgePage/detail"));
const FilesUpload = lazy(() => import("@/pages/KnowledgePage/filesUpload"));
const QasPage = lazy(() => import("@/pages/KnowledgePage/qas"));
const LabelPage = lazy(() => import("@/pages/LabelPage"));
const TaskAppChats = lazy(() => import("@/pages/LabelPage/taskAppChats"));
const TaskApps = lazy(() => import("@/pages/LabelPage/taskApps"));
const LogPage = lazy(() => import("@/pages/LogPage"));
const AppChatDetail = lazy(() => import("@/pages/LogPage/useAppLog/appChatDetail"));
const Doc = lazy(() => import("@/pages/ModelPage/doc"));
const Finetune = lazy(() => import("@/pages/ModelPage/finetune").then(module => ({ default: module.Finetune })));
const Management = lazy(() => import("@/pages/ModelPage/manage"));
const Report = lazy(() => import("@/pages/Report"));
const SystemPage = lazy(() => import("@/pages/SystemPage"));
const ResoucePage = lazy(() => import("@/pages/resoucePage"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));

const baseConfig = {
  //@ts-ignore
  basename: __APP_ENV__.BASE_URL
}

const RedirectToExternalLink = () => {
  useEffect(() => {
    window.location.href = window.location.origin + '/workspace/';
  }, []);

  return null;
};

const privateRouter = [
  { path: "/", element: <RedirectToExternalLink /> },
  {
    path: "/",
    element: <MainLayout />,
    errorElement: <RouteErrorBoundary />,
    children: [
      // { path: "", element: <SkillChatPage />, },
      { path: "filelib", element: <KnowledgePage />, permission: 'knowledge', },
      { path: "filelib/:id", element: <FilesPage />, permission: 'knowledge', },
      { path: "filelib/upload/:id", element: <FilesUpload />, permission: 'knowledge', },
      { path: "filelib/adjust/:fileId", element: <AdjustFilesUpload />, permission: 'knowledge', },
      { path: "filelib/qalib/:id", element: <QasPage />, permission: 'knowledge', },
      { path: "build/apps", element: <Apps />, permission: 'build', },
      // { path: "build/assist", element: <SkillAssisPage />, permission: 'build', },
      // { path: "build/skills", element: <SkillsPage />, permission: 'build', },
      // @ts-ignore
      { path: "build/tools", element: <SkillToolsPage />, permission: 'build', },
      { path: "build/client", element: <WorkBenchPage />, permission: 'build' },
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
      { path: "dashboard", element: <Dashboard /> },
      { path: "dashboard/:id", element: <EditorPage />, permission: 'dashboard', },
    ],
  },
  { path: "model/doc", element: <Doc />, errorElement: <RouteErrorBoundary /> },
  {
    path: "/skill/:id/",
    errorElement: <RouteErrorBoundary />,
    children: [
      { path: "", element: <SkillPage /> }
    ]
  },
  {
    path: "/flow/:id/",
    errorElement: <RouteErrorBoundary />,
    children: [
      { path: "", element: <FlowPage /> }
    ]
  },
  {
    path: "/assistant/:id/",
    errorElement: <RouteErrorBoundary />,
    children: [
      { path: "", element: <EditAssistantPage /> }
    ]
  },
  {
    path: "/resouce/:cid/:mid",
    errorElement: <RouteErrorBoundary />,
    element: <ResoucePage />
  },
  // 独立会话页
  { path: "/chat/assistant/auth/:id/", element: <ChatPro type={AppNumType.ASSISTANT} />, errorElement: <RouteErrorBoundary /> },
  { path: "/chat/flow/auth/:id/", element: <ChatPro type={AppNumType.FLOW} />, errorElement: <RouteErrorBoundary /> },
  { path: "/chat/skill/auth/:id/", element: <ChatPro />, errorElement: <RouteErrorBoundary /> },
  { path: "/chat", element: <SkillChatPage />, errorElement: <RouteErrorBoundary /> },
  { path: "/chat/:id/", element: <ChatShare />, errorElement: <RouteErrorBoundary /> },
  { path: "/chat/flow/:id/", element: <ChatShare type={AppNumType.FLOW} />, errorElement: <RouteErrorBoundary /> },
  { path: "/chat/assistant/:id/", element: <ChatAssitantShare />, errorElement: <RouteErrorBoundary /> },
  { path: "/report/:id/", element: <Report />, errorElement: <RouteErrorBoundary /> },
  { path: "/diff/:id/:vid/:cid", element: <DiffFlowPage />, errorElement: <RouteErrorBoundary /> },
  { path: "/reset", element: <ResetPwdPage />, errorElement: <RouteErrorBoundary /> },
  { path: "/403", element: <Page403 /> },
  { path: "/404", element: <Page404 /> },
  { path: "*", element: <Navigate to="/404" replace /> }
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
  { path: "/", element: <LoginPage />, errorElement: <RouteErrorBoundary /> },
  { path: "/reset", element: <ResetPwdPage />, errorElement: <RouteErrorBoundary /> },
  { path: "/chat/:id/", element: <ChatShare />, errorElement: <RouteErrorBoundary /> },
  { path: "/chat/flow/:id/", element: <ChatShare type={AppNumType.FLOW} />, errorElement: <RouteErrorBoundary /> },
  { path: "/chat/assistant/:id/", element: <ChatAssitantShare />, errorElement: <RouteErrorBoundary /> },
  { path: "/resouce/:cid/:mid", element: <ResoucePage />, errorElement: <RouteErrorBoundary /> },
  { path: "/403", element: <Page403 /> },
  { path: "*", element: <LoginPage /> }
],
  baseConfig)
