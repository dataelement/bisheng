import _ from "lodash";
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { unstable_useBlocker as useBlocker } from "react-router-dom";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Connection,
  Controls,
  Edge,
  EdgeChange,
  NodeChange,
  NodeDragHandler,
  OnEdgesDelete,
  OnSelectionChangeParams,
  SelectionDragHandler,
  addEdge,
  updateEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from "reactflow";
import GenericNode from "../../../../CustomNodes/GenericNode";
import Chat from "../../../../components/chatComponent";
import { Button } from "../../../../components/ui/button";
import { alertContext } from "../../../../contexts/alertContext";
import { locationContext } from "../../../../contexts/locationContext";
import { TabsContext } from "../../../../contexts/tabsContext";
import { typesContext } from "../../../../contexts/typesContext";
import { undoRedoContext } from "../../../../contexts/undoRedoContext";
import { APIClassType } from "../../../../types/api";
import { FlowType, NodeType } from "../../../../types/flow";
import { isValidConnection } from "../../../../utils";
import ConnectionLineComponent from "../ConnectionLineComponent";
import ExtraSidebar from "../extraSidebarComponent";
import { intersectArrays } from "../../../../util/utils";

const nodeTypes = {
  genericNode: GenericNode,
};

export default function Page({ flow, preFlow }: { flow: FlowType, preFlow: string }) {
  useEffect(() => {
    return () => {
      setReactFlowInstance(null) // 销毁reactflow实例
    }
  }, [])

  let {
    tabId,
    disableCopyPaste,
    lastCopiedSelection,
    saveFlow,
    uploadFlow,
    getNodeId,
    paste,
    setLastCopiedSelection,
    setTabsState,
  } = useContext(TabsContext);

  const { types, reactFlowInstance, setReactFlowInstance, templates } = useContext(typesContext);
  const reactFlowWrapper = useRef(null);

  const { takeSnapshot } = useContext(undoRedoContext);

  const position = useRef({ x: 0, y: 0 });
  const [lastSelection, setLastSelection] =
    useState<OnSelectionChangeParams>(null);

  // 快捷键
  useEffect(() => {
    // this effect is used to attach the global event handlers

    const onKeyDown = (event: KeyboardEvent) => {
      if (
        (event.ctrlKey || event.metaKey) &&
        event.key === "c" &&
        lastSelection &&
        !disableCopyPaste
      ) {
        event.preventDefault();
        setLastCopiedSelection(_.cloneDeep(lastSelection));
      }
      if (
        (event.ctrlKey || event.metaKey) &&
        event.key === "v" &&
        lastCopiedSelection &&
        !disableCopyPaste
      ) {
        event.preventDefault();
        let bounds = reactFlowWrapper.current.getBoundingClientRect();
        paste(lastCopiedSelection, {
          x: position.current.x - bounds.left,
          y: position.current.y - bounds.top,
        });
      }
      if (
        (event.ctrlKey || event.metaKey) &&
        event.key === "g" &&
        lastSelection
      ) {
        event.preventDefault();
        // addFlow(newFlow, false);
      }
    };
    const handleMouseMove = (event) => {
      position.current = { x: event.clientX, y: event.clientY };
    };

    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("mousemove", handleMouseMove);

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("mousemove", handleMouseMove);
    };
  }, [position, lastCopiedSelection, lastSelection]);

  // const [selectionMenuVisible, setSelectionMenuVisible] = useState(false);

  const { setExtraComponent, setExtraNavigation } = useContext(locationContext);
  const { setErrorData } = useContext(alertContext);
  const [nodes, setNodes, onNodesChange] = useNodesState(
    flow.data?.nodes ?? []
  );
  const [edges, setEdges, onEdgesChange] = useEdgesState(
    flow.data?.edges ?? []
  );
  const { setViewport } = useReactFlow();
  const edgeUpdateSuccessful = useRef(true);
  useEffect(() => {
    if (reactFlowInstance && flow) {
      flow.data = reactFlowInstance.toObject();
      // updateFlow(flow);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges]);
  //update flow when tabs change
  useEffect(() => {
    setNodes(flow?.data?.nodes ?? []);
    setEdges(flow?.data?.edges ?? []);
    if (reactFlowInstance) {
      setViewport(flow?.data?.viewport ?? { x: 1, y: 0, zoom: 0.5 });
      reactFlowInstance.fitView();
    }
  }, [flow, reactFlowInstance, setEdges, setNodes, setViewport]);
  //set extra sidebar
  useEffect(() => {
    setExtraComponent(<ExtraSidebar />);
    setExtraNavigation({ title: "Components" });
  }, [setExtraComponent, setExtraNavigation]);

  const onEdgesChangeMod = useCallback(
    (s: EdgeChange[]) => {
      onEdgesChange(s);
      setNodes((x) => {
        let newX = _.cloneDeep(x);
        return newX;
      });
      setTabsState((prev) => {
        return {
          ...prev,
          [tabId]: {
            ...prev[tabId],
            isPending: true,
          },
        };
      });
    },
    [onEdgesChange, setNodes, setTabsState, tabId]
  );

  const onNodesChangeMod = useCallback(
    (s: NodeChange[]) => {
      onNodesChange(s);
      setTabsState((prev) => {
        return {
          ...prev,
          [tabId]: {
            ...prev[tabId],
            isPending: true,
          },
        };
      });
    },
    [onNodesChange, setTabsState, tabId]
  );

  const onConnect = useCallback(
    (params: Connection) => {
      takeSnapshot();
      let hasInputNodeEdg = false
      setEdges((eds) => {
        // const moreTarget = eds.find(el => el.source === params.source)
        // hasInputNodeEdg = moreTarget && params.source.indexOf('InputFileNode') === 0
        // 限制InputFileNode节点只有一个下游
        // hasInputNodeEdg ? eds : 
        return addEdge(
          {
            ...params,
            style: { stroke: "#555" },
            className:
              (params.targetHandle.split("|")[0] === "Text"
                ? "stroke-foreground "
                : "stroke-foreground ") + " stroke-connection",
            // type: 'smoothstep',
            animated: true // params.targetHandle.split("|")[0] === "Text",
          },
          eds
        )
      });

      setNodes((x) => {
        let newX = _.cloneDeep(x);
        // inputFileNode类型跟随下游组件决定上传文件类型
        const inputNodeId = params.source
        if (inputNodeId.split('-')[0] === 'InputFileNode') {
          const inputNode = newX.find(el => el.id === params.source);
          const nextEdgs = [...edges, params].filter(el => el.source === params.source);
          const targetNodes = newX.filter(el => nextEdgs.find(edg => edg.target === el.id));
          // 取下游节点交集
          let result = intersectArrays(...targetNodes.map(el => el.data.node.template.file_path.fileTypes))
          result = result.length ? result : ['xxx'] // 无效后缀
          inputNode.data.node.template.file_path.fileTypes = result
          inputNode.data.node.template.file_path.suffixes = result.map(el => `.${el}`) // 上传文件类型；
        }
        return newX;
      });
    },
    [setEdges, setNodes, takeSnapshot]
  );

  const onNodeDragStart: NodeDragHandler = useCallback(() => {
    // 👇 make dragging a node undoable
    takeSnapshot();
    // 👉 you can place your event handlers here
  }, [takeSnapshot]);

  const onSelectionDragStart: SelectionDragHandler = useCallback(() => {
    // 👇 make dragging a selection undoable
    takeSnapshot();
  }, [takeSnapshot]);

  const onEdgesDelete: OnEdgesDelete = useCallback(() => {
    // 👇 make deleting edges undoable
    takeSnapshot();
  }, [takeSnapshot]);

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    if (event.dataTransfer.types.some((t) => t === "nodedata")) {
      event.dataTransfer.dropEffect = "move";
    } else {
      event.dataTransfer.dropEffect = "copy";
    }
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      if (event.dataTransfer.types.some((t) => t === "nodedata")) {
        takeSnapshot();

        // Get the current bounds of the ReactFlow wrapper element
        const reactflowBounds =
          reactFlowWrapper.current.getBoundingClientRect();

        // Extract the data from the drag event and parse it as a JSON object
        let data: { type: string; node?: APIClassType } = JSON.parse(
          event.dataTransfer.getData("nodedata")
        );

        // If data type is not "chatInput" or if there are no "chatInputNode" nodes present in the ReactFlow instance, create a new node
        // Calculate the position where the node should be created
        const position = reactFlowInstance.project({
          x: event.clientX - reactflowBounds.left,
          y: event.clientY - reactflowBounds.top,
        });

        // Generate a unique node ID
        let { type } = data;
        let newId = getNodeId(type);
        let newNode: NodeType;

        if (data.type !== "groupNode") {
          // Create a new node object
          newNode = {
            id: newId,
            type: "genericNode",
            position,
            data: {
              ...data,
              id: newId,
              value: null,
            },
          };
        } else {
          // Create a new node object
          newNode = {
            id: newId,
            type: "genericNode",
            position,
            data: {
              ...data,
              id: newId,
              value: null,
            },
          };

          // Add the new node to the list of nodes in state
        }
        setNodes((nds) => nds.concat(newNode));
      } else if (event.dataTransfer.types.some((t) => t === "Files")) {
        takeSnapshot();
        uploadFlow(false, event.dataTransfer.files.item(0));
      }
    },
    // Specify dependencies for useCallback
    [getNodeId, reactFlowInstance, setNodes, takeSnapshot]
  );

  const onDelete = useCallback(
    (mynodes) => {
      takeSnapshot();
      setEdges(
        edges.filter(
          (ns) => !mynodes.some((n) => ns.source === n.id || ns.target === n.id)
        )
      );
    },
    [takeSnapshot, edges, setEdges]
  );

  const onEdgeUpdateStart = useCallback(() => {
    edgeUpdateSuccessful.current = false;
  }, []);

  const onEdgeUpdate = useCallback(
    (oldEdge: Edge, newConnection: Connection) => {
      if (isValidConnection(newConnection, reactFlowInstance)) {
        edgeUpdateSuccessful.current = true;
        setEdges((els) => updateEdge(oldEdge, newConnection, els));
      }
    },
    [reactFlowInstance, setEdges]
  );

  const onEdgeUpdateEnd = useCallback((_, edge) => {
    if (!edgeUpdateSuccessful.current) {
      setEdges((eds) => eds.filter((e) => e.id !== edge.id));
    }

    edgeUpdateSuccessful.current = true;
  }, []);

  const [selectionEnded, setSelectionEnded] = useState(false);

  const onSelectionEnd = useCallback(() => {
    setSelectionEnded(true);
  }, []);
  const onSelectionStart = useCallback((event) => {
    event.preventDefault();
    setSelectionEnded(false);
  }, []);

  // Workaround to show the menu only after the selection has ended.
  // useEffect(() => {
  //   if (selectionEnded && lastSelection && lastSelection.nodes.length > 1) {
  //     setSelectionMenuVisible(true);
  //   } else {
  //     setSelectionMenuVisible(false);
  //   }
  // }, [selectionEnded, lastSelection]);

  const onSelectionChange = useCallback((flow) => {
    setLastSelection(flow);
  }, []);

  const { setDisableCopyPaste } = useContext(TabsContext);

  const { t } = useTranslation()

  // 离开提示保存
  useEffect(() => {
    const fun = (e) => {
      var confirmationMessage = `${t('flow.unsavedChangesConfirmation')}`;
      (e || window.event).returnValue = confirmationMessage; // Compatible with different browsers
      return confirmationMessage;
    }
    window.addEventListener('beforeunload', fun);
    return () => { window.removeEventListener('beforeunload', fun) }
  }, [])

  const hasChange = useMemo(() => {
    if (!flow.data) return false
    const oldFlowData = JSON.parse(preFlow)
    if (!oldFlowData) return true
    // 比较新旧
    const { edges, nodes } = flow.data
    const { edges: oldEdges, nodes: oldNodes } = oldFlowData
    return !(_.isEqual(edges, oldEdges) && _.isEqual(nodes, oldNodes))
  }, [preFlow, flow.data])

  const blocker = useBlocker(hasChange);
  // 离开并保存
  const handleSaveAndClose = async () => {
    await saveFlow(flow)
    blocker.proceed?.()
  }

  return (
    <div className="flex h-full overflow-hidden">
      <ExtraSidebar flow={flow} />
      {/* Main area */}
      <main className="flex flex-1">
        {/* Primary column */}
        <div className="h-full w-full">
          <div className="h-full w-full" ref={reactFlowWrapper}>
            {Object.keys(templates).length > 0 && Object.keys(types).length > 0 ? (
              <div className="h-full w-full">
                <ReactFlow
                  nodes={nodes}
                  onMove={() => {
                    if (reactFlowInstance)
                      flow = { ...flow, data: reactFlowInstance.toObject() }
                    // updateFlow({
                    //   ...flow,
                    //   data: reactFlowInstance.toObject()
                    // });
                  }}
                  edges={edges}
                  onPaneClick={() => {
                    setDisableCopyPaste(false);
                  }}
                  onPaneMouseLeave={() => {
                    setDisableCopyPaste(true);
                  }}
                  onPaneMouseEnter={() => {
                    setDisableCopyPaste(false);
                  }}
                  onNodesChange={onNodesChangeMod}
                  onEdgesChange={onEdgesChangeMod}
                  onConnect={onConnect}
                  disableKeyboardA11y={true}
                  onInit={setReactFlowInstance}
                  nodeTypes={nodeTypes}
                  onEdgeUpdate={onEdgeUpdate}
                  onEdgeUpdateStart={onEdgeUpdateStart}
                  onEdgeUpdateEnd={onEdgeUpdateEnd}
                  onNodeDragStart={onNodeDragStart}
                  onSelectionDragStart={onSelectionDragStart}
                  onSelectionEnd={onSelectionEnd}
                  onSelectionStart={onSelectionStart}
                  onEdgesDelete={onEdgesDelete}
                  connectionLineComponent={ConnectionLineComponent}
                  onDragOver={onDragOver}
                  onDrop={onDrop}
                  onNodesDelete={onDelete}
                  onSelectionChange={onSelectionChange}
                  nodesDraggable={!disableCopyPaste}
                  panOnDrag={!disableCopyPaste}
                  zoomOnDoubleClick={!disableCopyPaste}
                  className="theme-attribution"
                  minZoom={0.01}
                  maxZoom={8}
                  fitView
                >
                  <Background className="bg-gray-0 dark:bg-gray-950" color='#999' variant={BackgroundVariant.Dots} />
                  <Controls showInteractive={false}
                    className="bg-muted fill-foreground stroke-foreground text-primary
                   [&>button]:border-b-border hover:[&>button]:bg-border"
                  ></Controls>
                </ReactFlow>
                <Chat flow={flow} reactFlowInstance={reactFlowInstance} />
                <p className="absolute top-0 left-[220px] text-xs mt-2 text-gray-500">{flow.name}</p>
              </div>
            ) : (
              <></>
            )}
          </div>
        </div>
      </main>
      {/* 删除确认 */}
      <dialog className={`modal ${blocker.state === "blocked" && 'modal-open'}`}>
        <form method="dialog" className="modal-box w-[360px] bg-[#fff] shadow-lg dark:bg-background">
          <h3 className="font-bold text-lg">{t('prompt')}</h3>
          <p className="py-4">{t('flow.unsavedChangesConfirmation')}</p>
          <div className="modal-action">
            <Button className="h-8 rounded-full" variant="outline" onClick={() => blocker.reset?.()}>{t('cancel')}</Button>
            <Button className="h-8 rounded-full" variant="destructive" onClick={() => blocker.proceed?.()}>{t('flow.leave')}</Button>
            <Button className="h-8 rounded-full" onClick={handleSaveAndClose}>{t('flow.leaveAndSave')}</Button>
          </div>
        </form>
      </dialog>
    </div>
  );
}
