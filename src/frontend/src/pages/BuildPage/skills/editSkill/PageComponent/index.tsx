import GenericNode from "@/CustomNodes/GenericNode";
import ApiMainPage from "@/components/bs-comp/apiComponent";
import { Badge } from "@/components/bs-ui/badge";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import Chat from "@/components/chatComponent";
import { alertContext } from "@/contexts/alertContext";
import { TabsContext } from "@/contexts/tabsContext";
import { typesContext } from "@/contexts/typesContext";
import { undoRedoContext } from "@/contexts/undoRedoContext";
import { updateVersion } from "@/controllers/API/flow";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { APIClassType } from "@/types/api";
import { FlowType, NodeType } from "@/types/flow";
import { generateFlow, generateNodeFromFlow, reconnectEdges, validateSelection } from "@/util/reactflowUtils";
import { intersectArrays } from "@/util/utils";
import { isValidConnection } from "@/utils";
import cloneDeep from "lodash-es/cloneDeep";
import isEqual from "lodash-es/isEqual";
import { Layers } from "lucide-react";
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { unstable_useBlocker as useBlocker } from "react-router-dom";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Connection,
  Controls,
  Edge,
  EdgeChange,
  NodeChange,
  OnEdgesDelete,
  OnSelectionChangeParams,
  SelectionDragHandler,
  addEdge,
  reconnectEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from "@xyflow/react";
import ConnectionLineComponent from "../ConnectionLineComponent";
import Header from "../Header";
import SelectionMenu from "../SelectionMenuComponent";
import ExtraSidebar from "../extraSidebarComponent";


const nodeTypes = { genericNode: GenericNode };
export default function Page({ flow, preFlow }: { flow: FlowType, preFlow: string }) {

  let {
    version,
    setFlow,
    setTabsState,
    saveFlow,
    uploadFlow,
    getNodeId,
  } = useContext(TabsContext);
  const { setErrorData } = useContext(alertContext);


  const reactFlowWrapper = useRef(null);
  const { data, types, reactFlowInstance, setReactFlowInstance, templates } = useContext(typesContext);
  useEffect(() => {
    return () => {
      setReactFlowInstance(null) // 销毁reactflow实例
    }
  }, [])

  // 记录快照
  const { takeSnapshot } = useContext(undoRedoContext);
  // 快捷键
  const { keyBoardPanneRef, lastSelection, setLastSelection } = useKeyBoard(reactFlowWrapper)
  const onSelectionChange = useCallback((flow) => {
    setLastSelection(flow);
  }, []);

  const [selectionMenuVisible, setSelectionMenuVisible] = useState(false);
  const [selectionEnded, setSelectionEnded] = useState(true);

  // Workaround to show the menu only after the selection has ended.
  useEffect(() => {
    if (selectionEnded && lastSelection && lastSelection.nodes.length > 1) {
      setSelectionMenuVisible(true);
    } else {
      setSelectionMenuVisible(false);
    }
  }, [selectionEnded, lastSelection]);

  const [nodes, setNodes, onNodesChange] = useNodesState(
    flow.data?.nodes ?? []
  );
  const [edges, setEdges, onEdgesChange] = useEdgesState(
    flow.data?.edges ?? []
  );
  const { setViewport } = useReactFlow();
  useEffect(() => {
    if (reactFlowInstance && flow) {
      // 节点变化update flow(唯一修改口)
      flow.data = reactFlowInstance.toObject();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    /**
     * 由于flow模块设计问题，临时通过把flow挂在到window上，来提供 reactflow 节点 做重复id校验使用
     */
    window._flow = flow;
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

  const onEdgesChangeMod = useCallback(
    (s: EdgeChange[]) => {
      onEdgesChange(s);
      setNodes((x) => {
        let newX = cloneDeep(x);
        return newX;
      });
      setTabsState((prev) => {
        return {
          ...prev,
          [flow.id]: {
            ...prev[flow.id],
            isPending: true,
          },
        };
      });
    },
    [onEdgesChange, setNodes, setTabsState, flow.id]
  );

  const onNodesChangeMod = useCallback(
    (s: NodeChange[]) => {
      onNodesChange(s);
      setTabsState((prev) => {
        return {
          ...prev,
          [flow.id]: {
            ...prev[flow.id],
            isPending: true,
          },
        };
      });
    },
    [onNodesChange, setTabsState, flow.id]
  );

  const onConnect = useCallback(
    (params: Connection) => {
      takeSnapshot();
      setEdges((eds) => {
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
        let newX = cloneDeep(x);
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

  const onNodeDragStart = useCallback(() => {
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
        const reactflowBounds = reactFlowWrapper.current.getBoundingClientRect();

        // Extract the data from the drag event and parse it as a JSON object
        let data: { type: string; node?: APIClassType } = JSON.parse(
          event.dataTransfer.getData("nodedata")
        );

        // If data type is not "chatInput" or if there are no "chatInputNode" nodes present in the ReactFlow instance, create a new node
        // Calculate the position where the node should be created
        const position = reactFlowInstance.screenToFlowPosition({
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
            data: { ...data, id: newId, value: null }
          };
        } else {
          // Create a new node object
          newNode = {
            id: newId,
            type: "genericNode",
            position,
            data: { ...data, id: newId, value: null }
          };
          // Add the new node to the list of nodes in state
        }
        setNodes((nds) => nds.concat(newNode));
      } else if (event.dataTransfer.types.some((t) => t === "Files")) {
        // 拖拽上传技能
        takeSnapshot();
        uploadFlow(event.dataTransfer.files.item(0));
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

  const edgeUpdateSuccessful = useRef(true);
  const onEdgeUpdateStart = useCallback(() => {
    edgeUpdateSuccessful.current = false;
  }, []);

  const onEdgeUpdate = useCallback(
    (oldEdge: Edge, newConnection: Connection) => {
      if (isValidConnection(newConnection, reactFlowInstance)) {
        edgeUpdateSuccessful.current = true;
        setEdges((els) => reconnectEdge(oldEdge, newConnection, els));
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

  const { t } = useTranslation()
  const blocker = useBeforeUnload(flow, preFlow)

  // 离开并保存
  const handleSaveAndClose = async () => {
    setFlow('leave and save', { ...flow })

    await captureAndAlertRequestErrorHoc(updateVersion(version.id, { name: version.name, description: '', data: flow.data }))
    blocker.proceed?.()
  }

  // 修改组件id
  useEffect(() => {
    const handleChangeId = (data) => {
      const detail = data.detail
      const node = flow.data.nodes.find((node) => node.data.id === detail[1])
      node.id = detail[0]
      node.data.id = detail[0]
      // 更新线上 id 信息
      flow.data.edges.forEach(edge => {
        ['id', 'source', 'sourceHandle', 'target', 'targetHandle'].forEach(prop => {
          if (edge[prop]) {
            edge[prop] = edge[prop].replaceAll(detail[1], detail[0]);
          }
        });
      });
      // TODO 修改 setNodes 来更新
      setFlow('changeid', { ...flow })
    }
    document.addEventListener('idChange', handleChangeId)
    return () => document.removeEventListener('idChange', handleChangeId)
  }, [flow.data]); // 修改 id后, 需要监听 data这一层

  const [showApiPage, setShowApiPage] = useState(false)
  return (
    <div id="flow-page" className="flex flex-col h-full overflow-hidden">
      <Header flow={flow} onTabChange={(t) => setShowApiPage(t === 'api')}></Header>
      <div className={`flex flex-1 min-h-0 overflow-hidden ${showApiPage ? 'hidden' : ''}`}>
        {Object.keys(data).length ? <ExtraSidebar flow={flow} /> : <></>}
        {/* Main area */}
        <main className="flex flex-1" ref={keyBoardPanneRef}>
          {/* Primary column */}
          <div className="h-full w-full">
            <div className="h-full w-full" ref={reactFlowWrapper}>
              {Object.keys(templates).length > 0 && Object.keys(types).length > 0 ? (
                <div className="h-full w-full">
                  <ReactFlow
                    nodes={nodes}
                    edges={edges}
                    onMove={() => {
                      if (reactFlowInstance)
                        // 无用 待删
                        flow = { ...flow, data: reactFlowInstance.toObject() }
                    }}
                    onNodesChange={onNodesChangeMod}
                    onEdgesChange={onEdgesChangeMod}
                    onConnect={onConnect}
                    disableKeyboardA11y={true}
                    onInit={setReactFlowInstance}
                    nodeTypes={nodeTypes}
                    onReconnect={onEdgeUpdate}
                    onReconnectStart={onEdgeUpdateStart}
                    onReconnectEnd={onEdgeUpdateEnd}
                    onNodeDragStart={onNodeDragStart}
                    onSelectionDragStart={onSelectionDragStart}
                    onSelectionStart={(e) => { e.preventDefault(); setSelectionEnded(false) }}
                    onSelectionEnd={() => setSelectionEnded(true)}
                    onEdgesDelete={onEdgesDelete}
                    connectionLineComponent={ConnectionLineComponent}
                    onDragOver={onDragOver}
                    onDrop={onDrop}
                    onNodesDelete={onDelete}
                    onSelectionChange={onSelectionChange}
                    className="theme-attribution"
                    minZoom={0.01}
                    maxZoom={8}
                    fitView
                  >
                    <Background className="bg-gray-100 dark:bg-gray-950" color='#999' variant={BackgroundVariant.Dots} />
                    <Controls showInteractive={false}
                      className="bg-muted fill-foreground stroke-foreground text-primary
                   [&>button]:border-b-border hover:[&>button]:bg-border"
                    ></Controls>
                    <SelectionMenu
                      isVisible={selectionMenuVisible}
                      nodes={lastSelection?.nodes}
                      onClick={() => {
                        takeSnapshot();
                        const valiDateRes = validateSelection(lastSelection!, edges)
                        if (valiDateRes.length === 0) {
                          // groupFlow
                          const { newFlow, removedEdges } = generateFlow(
                            lastSelection!,
                            nodes,
                            edges,
                            ''
                          );
                          // newGroupNode（inset groupFlow）
                          const newGroupNode = generateNodeFromFlow(
                            newFlow,
                            getNodeId
                          );
                          // group之外的线
                          const newEdges = reconnectEdges(
                            newGroupNode,
                            removedEdges
                          );
                          // 更新节点，过滤重复 node
                          setNodes((oldNodes) => [
                            ...oldNodes.filter(
                              (oldNodes) =>
                                !lastSelection?.nodes.some(
                                  (selectionNode) =>
                                    selectionNode.id === oldNodes.id
                                )
                            ),
                            newGroupNode,
                          ]);
                          setEdges((oldEdges) => [
                            ...oldEdges.filter(
                              (oldEdge) =>
                                !lastSelection!.nodes.some(
                                  (selectionNode) =>
                                    selectionNode.id === oldEdge.target ||
                                    selectionNode.id === oldEdge.source
                                )
                            ),
                            ...newEdges,
                          ]);
                        } else {
                          setErrorData({
                            title: "Invalid selection",
                            list: valiDateRes,
                          });
                        }
                      }}
                    />
                  </ReactFlow>
                  <Chat flow={flow} reactFlowInstance={reactFlowInstance} />
                  <div className="absolute top-20 left-[220px] text-xs mt-2 text-gray-500">
                    <p className="mb-2">{flow.name}</p>
                    <Badge variant="outline"><Layers className="mr-1 size-4" />{t('skills.currentVersion')}{version?.name}</Badge>
                  </div>
                </div>
              ) : (
                <></>
              )}
            </div>
          </div>
        </main>
      </div>
      <div className={`flex flex-1 min-h-0 overflow-hidden ${showApiPage ? '' : 'hidden'}`}>
        <ApiMainPage type={'flow'} />
      </div>
      {/* 删除确认 */}
      <Dialog open={blocker.state === "blocked"}>
        <DialogContent className="sm:max-w-[425px]" close={false}>
          <DialogHeader>
            <DialogTitle>{t('prompt')}</DialogTitle>
            <DialogDescription>{t('flow.unsavedChangesConfirmation')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button className="h-8" variant="outline" onClick={() => {
              const dom = document.getElementById("flow-page") as HTMLElement;
              blocker.reset?.()
              if (dom) dom.className = dom.className.replace('report-hidden', '');
            }}>{t('cancel')}</Button>
            <Button className="leave h-8" variant="destructive" onClick={() => blocker.proceed?.()}>{t('flow.leave')}</Button>
            <Button className="h-8" onClick={handleSaveAndClose}>{t('flow.leaveAndSave')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// 复制粘贴组件，支持跨技能粘贴
const useKeyBoard = (reactFlowWrapper) => {
  const keyBoardPanneRef = useRef(null)

  const position = useRef({ x: 0, y: 0 });
  const [lastSelection, setLastSelection] =
    useState<OnSelectionChangeParams | null>(null);
  let {
    lastCopiedSelection,
    paste,
    setLastCopiedSelection,
  } = useContext(TabsContext);

  useEffect(() => {
    // this effect is used to attach the global event handlers
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.target.tagName === 'INPUT') return // 排除输入框内复制粘贴

      if (
        (event.ctrlKey || event.metaKey) &&
        event.key === "c" &&
        lastSelection
      ) {
        event.preventDefault();
        setLastCopiedSelection(cloneDeep(lastSelection));
        // } else if (
        //   (event.ctrlKey || event.metaKey) &&
        //   event.key === "x" &&
        //   lastSelection
        // ) {
        //   event.preventDefault();
        //   setLastCopiedSelection(cloneDeep(lastSelection), true);
      } else if (
        (event.ctrlKey || event.metaKey) &&
        event.key === "v" &&
        lastCopiedSelection
      ) {
        event.preventDefault();
        let bounds = reactFlowWrapper.current.getBoundingClientRect();
        paste(lastCopiedSelection, {
          x: position.current.x - bounds.left,
          y: position.current.y - bounds.top,
        });
      } else if (
        (event.ctrlKey || event.metaKey) &&
        event.key === "g" &&
        lastSelection
      ) {
        event.preventDefault();
      }
    };
    const handleMouseMove = (event) => {
      position.current = { x: event.clientX, y: event.clientY };
    };

    keyBoardPanneRef.current.addEventListener("keydown", onKeyDown);
    keyBoardPanneRef.current.addEventListener("mousemove", handleMouseMove);

    return () => {
      keyBoardPanneRef.current?.removeEventListener("keydown", onKeyDown);
      keyBoardPanneRef.current?.removeEventListener("mousemove", handleMouseMove);
    };
  }, [position, lastCopiedSelection, lastSelection]);

  return { lastSelection, keyBoardPanneRef, setLastSelection }
}

// 离开页面保存提示
const useBeforeUnload = (flow, preFlow) => {
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
    return !(isEqual(edges, oldEdges) && isEqual(nodes, oldNodes))
  }, [preFlow, flow.data])

  return useBlocker(hasChange);
}