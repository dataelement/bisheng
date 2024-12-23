import ApiMainPage from "@/components/bs-comp/apiComponent";
import { generateUUID } from "@/components/bs-ui/utils";
import { WorkFlow, WorkflowNode } from "@/types/flow";
import { autoNodeName, initNode, useCopyPasteNode } from "@/util/flowUtils";
import { useUndoRedo } from "@/util/hook";
import { Background, BackgroundVariant, Connection, Controls, ReactFlow, addEdge, applyEdgeChanges, applyNodeChanges, useReactFlow } from '@xyflow/react';
import '@xyflow/react/dist/base.css';
import '@xyflow/react/dist/style.css';
import cloneDeep from "lodash-es/cloneDeep";
import { useCallback, useEffect, useRef, useState } from "react";
import CustomEdge from "./FlowEdge";
import FlowNode from "./FlowNode";
import Header from "./Header";
import Sidebar from "./Sidebar";
import useFlowStore from "./flowStore";

// 自定义组件
const nodeTypes = { flowNode: FlowNode };
// 流程编排面板
export default function Panne({ flow, preFlow }: { flow: WorkFlow, preFlow: string }) {
    const [reactFlowInstance, setReactFlowInstance] = useState(null);
    // 导入自适应布局
    const fitView = useFlowStore(state => state.fitView)
    useEffect(() => {
        if (reactFlowInstance) {
            setTimeout(() => {
                reactFlowInstance.fitView();
            }, 0);
        }
    }, [fitView])

    useEffect(() => {
        return () => {
            setReactFlowInstance(null) // 销毁reactflow实例
        }
    }, [])

    const { takeSnapshot } = useUndoRedo()

    const { reactFlowWrapper, nodes, edges, keyBoardPanneRef,
        setNodes, onNodesChange, onSelectionChange, onEdgesChange, onEdgeSelect, onConnect, onDragOver, onDrop } = useFlow(reactFlowInstance, flow, takeSnapshot)

    /**
     * 监听节点变化，更新flow数据
     * 用户手动修改节点，或者使用reactFlow实例的setNode、setEdge都会触发
     * 注意 这里是唯一修改flow的入口，禁止在其他位置修改 flow的引用
     */
    useEffect(() => {
        if (reactFlowInstance && flow) {
            console.log('数据更新 :>> ', reactFlowInstance.toObject());
            const { nodes, edges, viewport } = reactFlowInstance.toObject()
            flow.nodes = nodes
            flow.edges = edges
            flow.viewport = viewport
        }
    }, [nodes, edges]);

    const [dropdownOpenEdgeId, setDropdownOpenEdgeId] = useState(null); // 用于追踪当前打开菜单的连线ID
    // 处理点击加号按钮时的操作，打开或关闭菜单
    const handleButtonClick = (edgeId) => {
        if (dropdownOpenEdgeId === edgeId) {
            // 如果当前连线已经打开菜单，点击加号按钮会关闭菜单
            setDropdownOpenEdgeId(null);
        } else {
            // 如果当前连线没有打开菜单，点击加号按钮会打开菜单
            setDropdownOpenEdgeId(edgeId);
        }
    };

    const onNodeDragStart = useCallback(() => {
        // 👇 make dragging a node undoable
        takeSnapshot();
        // 👉 you can place your event handlers here
    }, [takeSnapshot]);

    const onSelectionDragStart = useCallback(() => {
        // 👇 make dragging a selection undoable
        takeSnapshot();
    }, [takeSnapshot]);

    const onEdgesDelete = useCallback(() => {
        // 👇 make deleting edges undoable
        takeSnapshot();
    }, [takeSnapshot]);

    const [showApiPage, setShowApiPage] = useState(false)

    return <div className="flex flex-col h-full overflow-hidden">
        <Header flow={flow} onTabChange={(type) => setShowApiPage('api' === type)} preFlow={preFlow}></Header>
        <div className={`flex-1 min-h-0 overflow-hidden ${showApiPage ? 'hidden' : ''} relative`}>
            <Sidebar onInitStartNode={node => {
                // start node
                const nodeId = `${node.type}_${generateUUID(5)}`;
                node.id = nodeId;
                if (!flow.nodes || flow.nodes.length === 0) {
                    setTimeout(() => {
                        setNodes([{ id: nodeId, type: 'flowNode', position: { x: window.innerWidth * 0.4, y: 20 }, data: node }]);
                    }, 500); // after init
                }
            }} />
            <main className="h-full flex flex-1 bg-gray-50" ref={keyBoardPanneRef}>
                <div className="size-full" ref={reactFlowWrapper}>
                    <div className="size-full">
                        <ReactFlow
                            nodes={nodes}
                            edges={edges}
                            onInit={setReactFlowInstance}
                            onNodesChange={onNodesChange} // rebuild?
                            onEdgesChange={onEdgesChange} // rebuild?
                            onConnect={onConnect}
                            nodeTypes={nodeTypes}
                            onPaneClick={() => {
                                setDropdownOpenEdgeId(null);
                                window.dispatchEvent(new CustomEvent("closeHandleMenu"));
                            }}
                            edgeTypes={{
                                customEdge: (edgeProps) => (
                                    <CustomEdge
                                        {...edgeProps}
                                        isDropdownOpen={dropdownOpenEdgeId === edgeProps.id}
                                        onButtonClick={handleButtonClick}
                                        onOptionSelect={(data) => { onEdgeSelect(data); setDropdownOpenEdgeId(null) }}
                                    />
                                ),
                            }}
                            minZoom={0.1}
                            maxZoom={8}
                            disableKeyboardA11y={true}
                            // fitView
                            className={window.ThemeStyle.bg === 'logo' && "flow-bg-logo"}
                            onDragOver={onDragOver}
                            onDrop={onDrop}
                            onSelectionChange={onSelectionChange}
                            onBeforeDelete={(e) =>
                                // 阻止start节点删除
                                !e.nodes.some(node => node.data.type === 'start')
                            }
                            onEdgesDelete={onEdgesDelete}
                            onNodeDragStart={onNodeDragStart} // 快照
                            onSelectionDragStart={onSelectionDragStart} // 快照
                            onNodesDelete={() => takeSnapshot(flow)} // 更新setEdges
                            // 自定义线组件
                            // connectionLineComponent={ConnectionLineComponent} 
                            // 校验连线合法性
                            // onReconnect={onEdgeUpdate} 
                            // onReconnectStart={onEdgeUpdateStart}
                            // onReconnectEnd={onEdgeUpdateEnd}

                            // 框选 (group)
                            // onSelectionStart={(e) => { e.preventDefault(); setSelectionEnded(false) }}
                            // onSelectionEnd={() => setSelectionEnded(true)}
                            style={{
                                backgroundImage: window.ThemeStyle.bg === 'gradient'
                                    && 'radial-gradient(circle at center bottom, rgba(2, 77, 227, 0.3) 2%, rgba(2, 77, 227, 0.2) 25%, rgba(2, 77, 227, 0.05) 60%, rgba(0, 0, 0, 0) 100%)',
                                backgroundRepeat: 'no-repeat',
                                backgroundSize: 'cover',
                            }}
                        >
                            <Background className="dark:bg-gray-950" color='#999' variant={BackgroundVariant.Dots} />
                            <Controls className="bg-muted [&>button]:border-b-border hover:[&>button]:bg-border"></Controls>
                        </ReactFlow>
                    </div>
                </div>
            </main>
        </div>
        <div className={`flex flex-1 min-h-0 overflow-hidden ${showApiPage ? '' : 'hidden'}`}>
            <ApiMainPage type={'flow'} />
        </div>
    </div>
};


const useFlow = (_reactFlowInstance, data, takeSnapshot) => {

    const reactFlowWrapper = useRef(null);

    const [nodes, setNodes] = useState(data.nodes);
    const [edges, setEdges] = useState(data.edges);
    const { setViewport } = useReactFlow();
    // console.log('nodes edges:>> ', nodes, edges);
    //update flow when tabs change
    useEffect(() => {
        setNodes(data?.nodes ?? []);
        setEdges(data?.edges ?? []);
        if (_reactFlowInstance) {
            setViewport(data?.viewport ?? { x: 140, y: 140, zoom: 0.5 });
            _reactFlowInstance.fitView();
        }
    }, [data, _reactFlowInstance, setEdges, setNodes, setViewport]);

    // 绑定快捷键
    const { keyBoardPanneRef, setLastSelection } = useKeyBoard(_reactFlowInstance, reactFlowWrapper, setNodes, setEdges)

    const onNodesChange = useCallback(
        (changes) => setNodes((nds) => applyNodeChanges(changes, nds)),
        [setNodes]
    );
    const onEdgesChange = useCallback(
        (changes) => setEdges((eds) => applyEdgeChanges(changes, eds)),
        [setEdges]
    );
    const onConnect = useCallback(
        (params: Connection) => {
            takeSnapshot()
            setEdges((eds) => {
                return addEdge(
                    {
                        ...params,
                        type: 'customEdge',
                        // style: { stroke: "#024de3", strokeWidth: 2 },
                        // className: 'stroke-foreground stroke-connection',
                        animated: true
                    },
                    eds
                )
            });
            setNodes((x) => cloneDeep(x));
        },
        [setEdges, setNodes, takeSnapshot]
    );

    // 拖拽结束样式
    const onDragOver = useCallback((event: React.DragEvent) => {
        event.preventDefault();
        if (event.dataTransfer.types.some((t) => t === "flownodedata")) {
            event.dataTransfer.dropEffect = "move";
        } else {
            event.dataTransfer.dropEffect = "copy";
        }
    }, []);
    const onDrop = useCallback(
        (event: React.DragEvent) => {
            event.preventDefault();
            if (event.dataTransfer.types.some((t) => t === "flownodedata")) {
                takeSnapshot();
                const reactflowBounds = reactFlowWrapper.current.getBoundingClientRect();
                let flowdata: { type: string; node?: WorkflowNode } = JSON.parse(
                    event.dataTransfer.getData("flownodedata")
                );

                const position = _reactFlowInstance.screenToFlowPosition({
                    x: event.clientX - reactflowBounds.left,
                    y: event.clientY - reactflowBounds.top,
                });

                const nodeId = `${flowdata.node.type}_${generateUUID(5)}`
                flowdata.node.id = nodeId
                // 增加节点
                setNodes((nds) => {
                    const newName = autoNodeName(nds, flowdata.node.name)
                    const newNode = initNode(flowdata.node)
                    newNode.name = newName
                    return nds.concat({ id: nodeId, type: 'flowNode', position, data: newNode })
                });
            } else if (event.dataTransfer.types.some((t) => t === "Files")) {
                // 拖拽上传
                // takeSnapshot();
                // uploadFlow(event.dataTransfer.files.item(0));
            }
        },
        // Specify dependencies for useCallback
        [setNodes, _reactFlowInstance, takeSnapshot]
    );

    const onEdgeSelect = (obj) => {
        takeSnapshot()
        const { node, edgeId, position } = obj
        let flowdata: { type: string; node: WorkflowNode } = cloneDeep(node)
        const nodeId = `${flowdata.node.type}_${generateUUID(5)}`
        flowdata.node.id = nodeId
        // 增加节点
        setNodes((nds) => {
            const newName = autoNodeName(nds, flowdata.node.name)
            const newNode = initNode(flowdata.node)
            newNode.name = newName
            return nds.concat({
                id: nodeId, type: 'flowNode', position: {
                    x: position.x - 160,
                    y: position.y - 100,
                }, data: newNode
            })
        });
        // 增加边
        setEdges((eds) => {
            const edge = eds.find(el => el.id === edgeId)
            const leftEdge = { ...edge, selected: false, target: nodeId, id: `xy-edge__${edge.source}${edge.sourceHandle}-${nodeId}${edge.targetHandle}` }
            const rightEdge = { ...edge, selected: false, source: nodeId, sourceHandle: "right_handle", id: `xy-edge__${nodeId}right_handle-${edge.target}${edge.targetHandle}` }

            return eds
                .filter(el => el.id !== edgeId)
                .concat(leftEdge, rightEdge);
        })
    }

    // 监听来自自定义节点的Chang value
    useEffect(() => {
        // 定义事件监听器
        const handleNodeUpdate = (event) => {
            const { nodeId, newData } = event.detail;
            // 根据 nodeId 和 newData 更新节点状态
            setNodes((nds) =>
                nds.map((node) =>
                    node.id === nodeId ? { ...node, data: { ...node.data, ...newData } } : node
                )
            );
        };
        // del node
        const handleNodeDelete = (event) => {
            takeSnapshot()
            const nodeId = event.detail;
            setNodes((nodes) => nodes.filter((n) => n.id !== nodeId));
            setEdges((edges) => edges.filter((ns) => ns.source !== nodeId && ns.target !== nodeId));
        }

        // copy
        const handleCopy = (event) => {
            const nodeIds = event.detail;
            let nodes = _reactFlowInstance.getNodes();
            // let edges = _reactFlowInstance.getEdges();
            const newNodes = nodeIds.map(nodeId => {
                const node = nodes.find(n => n.id === nodeId);
                const newNodeId = `${node.type}_${generateUUID(5)}`
                // node.id = nodeId
                return {
                    id: newNodeId,
                    type: "flowNode",
                    position: {
                        x: node.position.x + 100,
                        y: node.position.y + 100,
                    },
                    data: {
                        ...cloneDeep(node.data),
                        id: newNodeId,
                    },
                    selected: false
                };
            });
            // 增加节点
            setNodes((nds) => {
                const _newNodes = newNodes.map(node => {
                    node.data.name = autoNodeName(nds, node.data.name)
                    return node
                })
                return nds.map((e) => ({ ...e, selected: false })).concat(_newNodes)
            });
        }
        // add node by handle
        const handleAddNode = (event) => {
            takeSnapshot()
            const { id, targetNode, isLeft, position } = event.detail;
            const newNode = cloneDeep(event.detail.newNode)
            window.dispatchEvent(new CustomEvent("closeHandleMenu"));

            const nodeId = `${newNode.type}_${generateUUID(5)}`
            newNode.node.id = nodeId
            const reactflowBounds = reactFlowWrapper.current.getBoundingClientRect();
            const pos = _reactFlowInstance.screenToFlowPosition({
                x: position.x - reactflowBounds.left + (isLeft ? -300 : 80),
                y: position.y - reactflowBounds.top,
            });
            // 增加节点
            setNodes((nds) => {
                const newName = autoNodeName(nds, newNode.node.name)
                const _newNode = initNode(newNode.node)
                _newNode.name = newName
                return nds.concat({
                    id: nodeId, type: 'flowNode', position: pos, data: _newNode
                })
            });

            // let data: { type: string; node: WorkflowNode } = node
            // data.node.id = nodeId
            // // 增加边
            const edge = isLeft ? {
                animated: true,
                id: `xy-edge__${nodeId}right_handle-${targetNode.id}left_handle`,
                source: nodeId,
                sourceHandle: "right_handle",
                target: targetNode.id,
                targetHandle: "left_handle",
                type: "customEdge"
            } : {
                animated: true,
                id: `xy-edge__${targetNode.id}${id || 'right_handle'}-${nodeId}left_handle`,
                source: targetNode.id,
                sourceHandle: id || "right_handle",
                target: nodeId,
                targetHandle: "left_handle",
                type: "customEdge"
            }
            setEdges((eds) => [
                edge,
                ...eds
            ]);
        }

        // 监听自定义事件
        window.addEventListener('nodeUpdate', handleNodeUpdate);
        window.addEventListener('nodeDelete', handleNodeDelete);
        window.addEventListener('nodeCopy', handleCopy);
        window.addEventListener('addNodeByHandle', handleAddNode);

        // 在组件卸载时移除事件监听
        return () => {
            window.removeEventListener('nodeUpdate', handleNodeUpdate);
            window.addEventListener('nodeDelete', handleNodeDelete);
            window.removeEventListener('nodeCopy', handleCopy);
            window.removeEventListener('addNodeByHandle', handleAddNode);
        };
    }, [_reactFlowInstance]);

    // 选中节点
    const onSelectionChange = useCallback((data) => {
        setLastSelection(data);
    }, []);

    return {
        reactFlowWrapper, nodes, edges, keyBoardPanneRef,
        onNodesChange, onEdgesChange, onConnect, onDragOver, onDrop, onSelectionChange, onEdgeSelect, setNodes
    }
}

// 复制粘贴组件，支持跨技能粘贴
const useKeyBoard = (_reactFlowInstance, reactFlowWrapper) => {
    const keyBoardPanneRef = useRef<HTMLDivElement>(null); // 绑定快捷键
    const [lastSelection, setLastSelection] = useState(null);
    const { setNodes, setEdges } = useReactFlow();

    useCopyPasteNode(keyBoardPanneRef.current, lastSelection, (newSelectNode, position) => {
        if (newSelectNode.nodes.some(node => node.data.type === 'start')) return
        let bounds = reactFlowWrapper.current.getBoundingClientRect();
        setNodes((nds) => {
            const newNodes = newSelectNode.nodes.map(node => {
                const newNode = cloneDeep(node)
                const nodeId = `${newNode.data.type}_${generateUUID(5)}`
                newNode.id = nodeId
                newNode.data.id = nodeId
                const newName = autoNodeName(nds, newNode.data.name)
                newNode.data.name = newName
                // newNode.selected = false

                newNode.position = _reactFlowInstance.screenToFlowPosition({
                    x: position.x - bounds.left,
                    y: position.y - bounds.top,
                });
                return newNode
            })
            return [...newNodes, ...nds]
        })
    }, (selectNode) => {
        // 删除线和node
        // takeSnapshot()
        const targetNodes = selectNode.nodes;
        const targetEdges = selectNode.edges;

        if (targetNodes.some(node => node.data.type === 'start')) return
        setNodes((nodes) => nodes.filter((n) => !targetNodes.some(el => el.id === n.id)));
        setEdges((edges) => edges.filter((ns) => !targetEdges.some(el => el.id === ns.id)));
    }, [_reactFlowInstance, setNodes])

    return { keyBoardPanneRef, setLastSelection }
}