import cloneDeep from "lodash-es/cloneDeep";
import { ReactNode, createContext, useContext, useState } from "react";
import { addEdge } from "@xyflow/react";
import { updateFlowApi } from "../controllers/API/flow";
import { APIClassType, APITemplateType } from "../types/api";
import { FlowType, FlowVersionItem, NodeType } from "../types/flow";
import { TabsContextType, TabsState } from "../types/tabs";
import { generateUUID, updateTemplate } from "../utils";
import { alertContext } from "./alertContext";
import { typesContext } from "./typesContext";
import { captureAndAlertRequestErrorHoc } from "../controllers/request";

const TabsContextInitialValue: TabsContextType = {
  flow: null,
  tabsState: {}, // keyform isPending
  setFlow: (ac, f) => { },
  setTabsState: (state: TabsState) => { },
  saveFlow: async (flow: FlowType) => Promise.resolve(),
  uploadFlow: () => { },
  setTweak: (tweak: any) => { },
  getTweak: [],
  // 跨组件粘贴
  lastCopiedSelection: null,
  setLastCopiedSelection: (selection: any) => { },
  downloadFlow: (flow: FlowType) => { },
  getNodeId: (nodeType: string) => "",
  paste: (
    selection: { nodes: any; edges: any },
    position: { x: number; y: number; paneX?: number; paneY?: number }
  ) => { },
  version: null,
  setVersion: (version: FlowVersionItem | null) => ""
};

export const TabsContext = createContext<TabsContextType>(
  TabsContextInitialValue
);

export function TabsProvider({ children }: { children: ReactNode }) {
  const [flow, setFlow] = useState<FlowType>(null);
  const [version, setVersion] = useState<FlowVersionItem | null>(null);
  // flowid: formKeysData
  const [tabsState, setTabsState] = useState<TabsState>({});
  const [lastCopiedSelection, setLastCopiedSelection] = useState(null);
  const [getTweak, setTweak] = useState([]);

  const { setErrorData, setNoticeData } = useContext(alertContext);
  const { templates, reactFlowInstance } = useContext(typesContext);

  async function saveFlow(flow: FlowType) {
    // save api
    const newFlow = await captureAndAlertRequestErrorHoc(updateFlowApi(flow))
    if (!newFlow) return null;
    console.log('action :>> ', 'save');
    setFlow(newFlow)
    setTabsState((prev) => {
      return {
        ...prev,
        [newFlow.id]: {
          ...prev[newFlow.id],
          isPending: false,
        },
      };
    });
    return newFlow
  }

  /**
   * Creates a file input and listens to a change event to upload a JSON flow file.
   * If the file type is application/json, the file is read and parsed into a JSON object.
   * The resulting JSON object is passed to the addFlow function.
   */
  function uploadFlow(file?: File) {
    if (file) {
      file.text().then((text) => {
        // parse the text into a JSON object
        let flow: FlowType = JSON.parse(text);
        // 粘贴
        paste(
          { nodes: flow.data.nodes, edges: flow.data.edges },
          { x: 10, y: 10 },
          true
        );
        // 覆盖
        // setFlow(flow);
      });
    } else {
      // create a file input
      const input = document.createElement("input");
      input.type = "file";
      input.accept = ".json";
      // add a change event listener to the file input
      input.onchange = (e: Event) => {
        // check if the file type is application/json
        if (
          (e.target as HTMLInputElement).files[0].type === "application/json"
        ) {
          // get the file from the file input
          const currentfile = (e.target as HTMLInputElement).files[0];
          // read the file as text
          currentfile.text().then((text) => {
            // parse the text into a JSON object
            let flow: FlowType = JSON.parse(text);
            // 粘贴
            paste(
              { nodes: flow.data.nodes, edges: flow.data.edges },
              { x: 10, y: 10 },
              true
            );
          });
        }
      };
      // trigger the file input click event to open the file dialog
      input.click();
    }
  }

  function getNodeId(nodeType: string) {
    return nodeType + "-" + generateUUID(5);
  }

  /**
 * Downloads the current flow as a JSON file
 */
  function downloadFlow(
    flow: FlowType,
    flowName: string,
    flowDescription?: string
  ) {
    // create a data URI with the current flow data
    const jsonString = `data:text/json;chatset=utf-8,${encodeURIComponent(
      JSON.stringify({ ...flow, name: flowName, description: flowDescription })
    )}`;

    // create a link element and set its properties
    const link = document.createElement("a");
    link.href = jsonString;
    link.download = `${flowName || flow.name}.json`;

    // simulate a click on the link element to trigger the download
    link.click();
    setNoticeData({
      title: "警告：关键数据，JSON 文件可能包含 API 密钥。",
    });
  }

  /**
 * Add a new flow to the list of flows.
 * @param flow Optional flow to add.
 */

  function paste(
    selectionInstance,
    position: { x: number; y: number; paneX?: number; paneY?: number },
    keepId: boolean = false // keep id
  ) {
    let minimumX = Infinity;
    let minimumY = Infinity;
    let idsMap = {};
    let nodes = reactFlowInstance.getNodes();
    let edges = reactFlowInstance.getEdges();
    selectionInstance.nodes.forEach((n) => {
      if (n.position.y < minimumY) {
        minimumY = n.position.y;
      }
      if (n.position.x < minimumX) {
        minimumX = n.position.x;
      }
    });

    const insidePosition = position.paneX
      ? { x: position.paneX + position.x, y: position.paneY + position.y }
      : reactFlowInstance.screenToFlowPosition({ x: position.x, y: position.y });

    selectionInstance.nodes.forEach((n: NodeType) => {
      // Generate a unique node ID
      let newId = getNodeId(n.data.type);
      // 保留原id； 重复 id除外
      if (keepId && !nodes.find(node => node.id === n.id)) {
        newId = n.id;
      }
      idsMap[n.id] = newId;

      // Create a new node object
      const newNode: NodeType = {
        id: newId,
        type: "genericNode",
        position: {
          x: insidePosition.x + n.position.x - minimumX,
          y: insidePosition.y + n.position.y - minimumY,
        },
        data: {
          ...cloneDeep(n.data),
          id: newId,
        },
      };

      // Add the new node to the list of nodes in state
      nodes = nodes
        .map((e) => ({ ...e, selected: false }))
        .concat({ ...newNode, selected: false });
    });
    console.log(nodes)
    reactFlowInstance.setNodes(nodes);

    selectionInstance.edges.forEach((e) => {
      let source = idsMap[e.source];
      let target = idsMap[e.target];
      let sourceHandleSplitted = e.sourceHandle.split("|");
      let sourceHandle =
        sourceHandleSplitted[0] +
        "|" +
        source +
        "|" +
        sourceHandleSplitted.slice(2).join("|");
      let targetHandleSplitted = e.targetHandle.split("|");
      let targetHandle =
        targetHandleSplitted.slice(0, -1).join("|") + "|" + target;
      let id =
        "reactflow__edge-" +
        source +
        sourceHandle +
        "-" +
        target +
        targetHandle;
      edges = addEdge(
        {
          source,
          target,
          sourceHandle,
          targetHandle,
          id,
          style: { stroke: "#555" },
          className:
            targetHandle.split("|")[0] === "Text"
              ? "stroke-gray-800 "
              : "stroke-gray-900 ",
          animated: targetHandle.split("|")[0] === "Text",
          selected: false,
        },
        edges.map((e) => ({ ...e, selected: false }))
      );
    });
    reactFlowInstance.setEdges(edges);
  }

  // --
  function updateNodeEdges(
    flow: FlowType,
    node: NodeType,
    template: APIClassType
  ) {
    flow.data.edges.forEach((edge) => {
      if (edge.source === node.id) {
        edge.sourceHandle = edge.sourceHandle
          .split("|")
          .slice(0, 2)
          .concat(template["base_classes"])
          .join("|");
      }
    });
  }

  function processFlowEdges(flow) {
    if (!flow.data || !flow.data.edges) return;
    flow.data.edges.forEach((edge) => {
      edge.className = "";
      edge.style = { stroke: "#555" };
    });
  }

  function processFlowNodes(flow) {
    if (!flow.data || !flow.data.nodes) return;
    flow.data.nodes.forEach((node: NodeType) => {
      const template = templates[node.data.type];
      if (!template) {
        // setErrorData({ title: `Unknown node type: ${node.data.type}` });
        console.warn(`Unknown node type: ${node.data.type}`)
        return;
      }
      if (Object.keys(template["template"]).length > 0) {
        node.data.node.display_name = template["display_name"] || node.data.type;
        node.data.node.base_classes = template["base_classes"];
        node.data.node.description = template["description"];
        node.data.node.documentation = template["documentation"];
        updateNodeEdges(flow, node, template);
        node.data.node.template = updateTemplate(
          template["template"] as unknown as APITemplateType,
          node.data.node.template as APITemplateType
        );
      }
    });
  }

  // 上线版本的版本 id
  const [onlineVid, setOnlineVid] = useState(0);
  const updateOnlineVid = (vid: number) => {
    setOnlineVid(flow.status === 2 ? vid : 0);
  }

  return (
    <TabsContext.Provider
      value={{
        flow,
        setFlow: (action, flow) => {
          console.log('action :>> ', action);
          if (action === "flow_init") {
            // 按模板矫正数据格式
            processFlowEdges(flow);
            processFlowNodes(flow);
          }

          setFlow(flow);
        },
        saveFlow,
        getTweak,
        setTweak,
        lastCopiedSelection,
        setLastCopiedSelection,
        downloadFlow,
        uploadFlow,
        getNodeId,
        tabsState,
        setTabsState,
        paste,
        version,
        setVersion,
        isOnlineVersion: () => version.id === onlineVid,
        updateOnlineVid
      }}
    >
      {children}
    </TabsContext.Provider>
  );
}
