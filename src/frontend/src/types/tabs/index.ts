import { Dispatch, SetStateAction } from "react";
import { FlowType, FlowVersionItem, TweaksType } from "../flow";

export type TabsContextType = {
  flow: FlowType | null;
  setFlow: (ac: string, t: FlowType) => void;
  saveFlow: (flow: FlowType) => Promise<any>;
  downloadFlow: (
    flow: FlowType,
    flowName: string,
    flowDescription?: string
  ) => void;
  uploadFlow: (file?: File) => void;
  getNodeId: (nodeType: string) => string;
  tabsState: TabsState;
  setTabsState: Dispatch<SetStateAction<TabsState>>;
  paste: (
    selection: { nodes: any; edges: any },
    position: { x: number; y: number; paneX?: number; paneY?: number }
  ) => void;
  lastCopiedSelection: { nodes: any; edges: any };
  setLastCopiedSelection: (selection: { nodes: any; edges: any }) => void;
  setTweak: (tweak: TweaksType) => void;
  getTweak: TweaksType[];
  setVersion: (version: FlowVersionItem | null) => {},
  version: FlowVersionItem
};

export type TabsState = {
  [key: string]: {
    isPending: boolean;
    formKeysData: {
      template?: string;
      input_keys?: Object[];
      memory_keys?: Array<string>;
      handle_keys?: Array<string>;
    };
  };
};
