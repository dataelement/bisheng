import cloneDeep from "lodash-es/cloneDeep";
import uniqueId from "lodash-es/uniqueId";
import { useContext, useEffect, useMemo, useState } from "react";
import { RouterProvider } from "react-router-dom";
import "./App.css";

import i18next from "i18next";
import { useTranslation } from "react-i18next";
import ErrorAlert from "./alerts/error";
import NoticeAlert from "./alerts/notice";
import SuccessAlert from "./alerts/success";
import { Toaster } from "./components/bs-ui/toast";
import { alertContext } from "./contexts/alertContext";
import { locationContext } from "./contexts/locationContext";
import { userContext } from "./contexts/userContext";
import { getAdminRouter, getPrivateRouter, publicRouter } from "./routes";
import { LoadingIcon } from "./components/bs-icons/loading";

export default function App() {
  let { setCurrent, setShowSideBar, setIsStackedOpen } = useContext(locationContext);
  // let location = useLocation();
  useEffect(() => {
    setCurrent(location.pathname.replace(/\/$/g, "").split("/"));
    setShowSideBar(true);
    setIsStackedOpen(true);
  }, [setCurrent, setIsStackedOpen, setShowSideBar]);
  const {
    errorData,
    errorOpen,
    setErrorOpen,
    noticeData,
    noticeOpen,
    setNoticeOpen,
    successData,
    successOpen,
    setErrorData,
    setSuccessOpen,
  } = useContext(alertContext);

  // Initialize state variable for the list of alerts
  const [alertsList, setAlertsList] = useState<
    Array<{
      type: string;
      data: { title: string; list?: Array<string>; link?: string };
      id: string;
    }>
  >([]);

  // Use effect hook to update alertsList when a new alert is added
  useEffect(() => {
    // If there is an error alert open with data, add it to the alertsList
    if (errorOpen && errorData) {
      if (
        alertsList.length > 0 &&
        JSON.stringify(alertsList[alertsList.length - 1].data) ===
        JSON.stringify(errorData)
      ) {
        return;
      }
      setErrorOpen(false);
      setAlertsList((old) => {
        let newAlertsList = [
          ...old,
          { type: "error", data: cloneDeep(errorData), id: uniqueId() },
        ];
        return newAlertsList;
      });
    }
    // If there is a notice alert open with data, add it to the alertsList
    else if (noticeOpen && noticeData) {
      if (
        alertsList.length > 0 &&
        JSON.stringify(alertsList[alertsList.length - 1].data) ===
        JSON.stringify(noticeData)
      ) {
        return;
      }
      setNoticeOpen(false);
      setAlertsList((old) => {
        let newAlertsList = [
          ...old,
          { type: "notice", data: cloneDeep(noticeData), id: uniqueId() },
        ];
        return newAlertsList;
      });
    }
    // If there is a success alert open with data, add it to the alertsList
    else if (successOpen && successData) {
      if (
        alertsList.length > 0 &&
        JSON.stringify(alertsList[alertsList.length - 1].data) ===
        JSON.stringify(successData)
      ) {
        return;
      }
      setSuccessOpen(false);
      setAlertsList((old) => {
        let newAlertsList = [
          ...old,
          { type: "success", data: cloneDeep(successData), id: uniqueId() },
        ];
        return newAlertsList;
      });
    }
  }, [
    errorData,
    errorOpen,
    noticeData,
    noticeOpen,
    setErrorOpen,
    setNoticeOpen,
    setSuccessOpen,
    successData,
    successOpen,
  ]);


  /**
   * 暴露弹窗全局使用
   **/
  useEffect(() => {
    window.errorAlerts = (errorList: string[]) => {
      setAlertsList((old) => {
        let newAlertsList = [
          ...old,
          { type: "error", data: { title: '', list: errorList }, id: uniqueId() },
        ];
        return newAlertsList;
      })
    }
  }, [])

  const removeAlert = (id: string) => {
    setAlertsList((prevAlertsList) =>
      prevAlertsList.filter((alert) => alert.id !== id)
    );
  };

  const { user, setUser } = useContext(userContext);

  // 退出
  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.ctrlKey && event.keyCode === 81) {
        setUser(null)
        localStorage.setItem('UUR_INFO', '')
      }
    };
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, []);

  // i18n title
  const { t } = useTranslation()
  useEffect(() => {
    document.title = t('title')
  }, [t])
  // init language
  useEffect(() => {
    const lang = user?.user_id ? localStorage.getItem('language-' + user.user_id) : null
    if (lang) {
      i18next.changeLanguage(lang)
    }
  }, [user])

  // 免登录列表
  const noAuthPages = ['chat', 'resouce']
  const path = location.pathname.split('/')?.[1] || ''

  // 动态路由根据权限
  const router = useMemo(() => {
    // return getAdminRouter()
    if (user && ['admin', 'group_admin'].includes(user.role)) return getAdminRouter()
    return user?.user_id ? getPrivateRouter(user.web_menu) : null
  }, [user])

  return (
    //need parent component with width and height
    <div className="flex h-full flex-col">
      {(user?.user_id || noAuthPages.includes(path)) && router ? <RouterProvider router={router} />
        : user ? <div className='absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared'>
          <LoadingIcon className="size-48 text-primary" />
        </div>
          : <RouterProvider router={publicRouter} />}
      <div></div>
      <div className="app-div" style={{ zIndex: 1000 }}>
        {alertsList.map((alert) => (
          <div key={alert.id}>
            {alert.type === "error" ? (
              <ErrorAlert
                key={alert.id}
                title={alert.data.title}
                list={alert.data.list}
                id={alert.id}
                removeAlert={removeAlert}
              />
            ) : alert.type === "notice" ? (
              <NoticeAlert
                key={alert.id}
                title={alert.data.title}
                link={alert.data.link}
                id={alert.id}
                removeAlert={removeAlert}
              />
            ) : (
              <SuccessAlert
                key={alert.id}
                title={alert.data.title}
                id={alert.id}
                removeAlert={removeAlert}
              />
            )}
          </div>
        ))}
      </div>
      {/* 新弹窗 */}
      <Toaster></Toaster>
    </div>
  );
}
