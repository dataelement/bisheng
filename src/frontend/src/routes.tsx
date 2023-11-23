import { Navigate, createBrowserRouter } from "react-router-dom";
import MainLayout from "./layout/MainLayout";
import FileLibPage from "./pages/FileLibPage";
import FilesPage from "./pages/FileLibPage/files";
import FlowPage from "./pages/FlowPage";
import HomePage from "./pages/MainPage";
import ModelPage from "./pages/ModelPage";
import SystemPage from "./pages/SystemPage";
import Doc from "./pages/ModelPage/doc";
import SkillChatPage from "./pages/SkillChatPage";
import SkillPage from "./pages/SkillPage";
import ChatShare from "./pages/SkillChatPage/chatShare";
import L2Edit from "./pages/SkillPage/l2Edit";
// import Report from "./pages/Report";

// react 与 react router dom版本不匹配
// const FileLibPage = lazy(() => import(/* webpackChunkName: "FileLibPage" */ "./pages/FileLibPage"));
// const FilesPage = lazy(() => import(/* webpackChunkName: "FilesPage" */ "./pages/FileLibPage/files"));
// const SkillPage = lazy(() => import(/* webpackChunkName: "SkillPage" */ "./pages/SkillPage"));
// const SkillChatPage = lazy(() => import(/* webpackChunkName: "SkillChatPage" */ "./pages/SkillChatPage"));
// const FileViewPage = lazy(() => import(/* webpackChunkName: "FileViewPage" */ "./pages/FileViewPage"));

const router = createBrowserRouter([
  {
    path: "/",
    element: <MainLayout />,
    children: [
      { path: "", element: <SkillChatPage /> },
      { path: "skill", element: <L2Edit /> },
      { path: "skill/:id", element: <L2Edit /> },
      { path: "filelib", element: <FileLibPage /> },
      { path: "filelib/:id", element: <FilesPage /> },
      { path: "skills", element: <SkillPage /> },
      { path: "model", element: <ModelPage /> },
      { path: "sys", element: <SystemPage /> },
    ],
  },
  { path: "model/doc", element: <Doc /> },
  {
    path: "/flow/:id/",
    children: [
      { path: "", element: <FlowPage /> }
    ]
  },
  // 独立会话页
  { path: "/chat", element: <SkillChatPage /> },
  { path: "/chat/:id/", element: <ChatShare /> },
  // { path: "/report/:id/", element: <Report /> },
  // { path: "/test", element: <Test /> },
  { path: "*", element: <Navigate to="/" replace /> },
  { path: "/home", element: <HomePage /> }
]);

export default router;
