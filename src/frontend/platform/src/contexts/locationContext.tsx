import { createContext, ReactNode, useEffect, useState } from "react";
import { getAppConfig, getWorkstationConfigApi } from "../controllers/API";

//types for location context
type locationContextType = {
  current: Array<string>;
  setCurrent: (newState: Array<string>) => void;
  isStackedOpen: boolean;
  setIsStackedOpen: (newState: boolean) => void;
  showSideBar: boolean;
  setShowSideBar: (newState: boolean) => void;
  extraNavigation: {
    title: string;
    options?: Array<{
      name: string;
      href: string;
      icon: any;
      children?: Array<any>;
    }>;
  };
  setExtraNavigation: (newState: {
    title: string;
    options?: Array<{
      name: string;
      href: string;
      icon: any;
      children?: Array<any>;
    }>;
  }) => void;
  extraComponent: any;
  setExtraComponent: (newState: any) => void;
  appConfig: any;
  reloadConfig: () => void
};

//initial value for location context
const initialValue = {
  //actual
  current: window.location.pathname.replace(/\/$/g, "").split("/"),
  isStackedOpen:
    window.innerWidth > 1024 && window.location.pathname.split("/")[1]
      ? true
      : false,
  setCurrent: () => { },
  setIsStackedOpen: () => { },
  showSideBar: window.location.pathname.split("/")[1] ? true : false,
  setShowSideBar: () => { },
  extraNavigation: { title: "" },
  setExtraNavigation: () => { },
  extraComponent: <></>,
  setExtraComponent: () => { },
  appConfig: { libAccepts: [] },
  reloadConfig: () => { }
};

export const locationContext = createContext<locationContextType>(initialValue);

export function LocationProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState(initialValue.current);
  const [isStackedOpen, setIsStackedOpen] = useState(
    initialValue.isStackedOpen
  );
  const [showSideBar, setShowSideBar] = useState(initialValue.showSideBar);
  const [extraNavigation, setExtraNavigation] = useState({ title: "" });
  const [extraComponent, setExtraComponent] = useState(<></>);
  const [appConfig, setAppConfig] = useState<any>({
    libAccepts: [],
    noFace: true,
    disableCopyFlowIds: [],
  })

  const loadConfig = () => {
    getAppConfig()
      .then(res => {
        // Set all config values that come from getAppConfig
        setAppConfig({
          isDev: res.env === 'dev',
          libAccepts: res.uns_support,
          officeUrl: res.office_url,
          dialogTips: res.dialog_tips,
          dialogQuickSearch: res.dialog_quick_search,
          websocketHost: res.websocket_url,
          isPro: !!res.pro,
          chatPrompt: !!res.application_usage_tips,
          securityCommitment: !!res.enable_security_commitment,
          noFace: !res.show_github_and_help,
          register: !!res.enable_registration,
          disableCopyFlowIds: res.disable_copy_flow_ids || [],
          uploadFileMaxSize: res.uploaded_files_maximum_size || 50,
          enableEtl4lm: res.enable_etl4lm
        });

        // backend version
        res.version && console.log(
          "%cversion " + res.version,
          "background-color:#024de3;color:#fff;font-weight:bold;font-size: 38px;" +
          "padding: 6px 12px;font-family:'american typewriter';text-shadow:1px 1px 3px black;"
        );

        // Then get workstation config separately
        return getWorkstationConfigApi()
          .then(bench => {
            // Only update the benchMenu property
            setAppConfig(prev => ({
              ...prev,
              benchMenu: bench?.menuShow || false
            }));
          })
          .catch(error => {
            console.error('Failed to get workstation config:', error);
            // Set default value for benchMenu if the request fails
            setAppConfig(prev => ({
              ...prev,
              benchMenu: false
            }));
          });
      })
      .catch(error => {
        console.error('Failed to get app config:', error);
        // You might want to set some default values here if the main config fails
      });
  }

  // 获取系统配置
  useEffect(() => {
    loadConfig()
  }, [])

  return (
    <locationContext.Provider
      value={{
        isStackedOpen,
        setIsStackedOpen,
        current,
        setCurrent,
        showSideBar,
        setShowSideBar,
        extraNavigation,
        setExtraNavigation,
        extraComponent,
        setExtraComponent,
        appConfig,
        reloadConfig: loadConfig,
      }}
    >
      {children}
    </locationContext.Provider>
  );
}
