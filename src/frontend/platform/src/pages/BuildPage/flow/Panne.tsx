import ApiMainPage from "@/components/bs-comp/apiComponent";
import { generateUUID } from "@/components/bs-ui/utils";
import { copyReportTemplate } from "@/controllers/API/workflow";
import { WorkFlow, WorkflowNode } from "@/types/flow";
import { autoNodeName, calculatePosition, filterUselessFlow, initNode, useCopyPasteNode } from "@/util/flowUtils";
import { useUndoRedo } from "@/util/hook";
import { Background, BackgroundVariant, Connection, ReactFlow, addEdge, applyEdgeChanges, applyNodeChanges, useReactFlow } from '@xyflow/react';
import '@xyflow/react/dist/base.css';
import '@xyflow/react/dist/style.css';
import cloneDeep from "lodash-es/cloneDeep";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Controls } from "./Controls";
import CustomEdge from "./FlowEdge";
import FlowNode from "./FlowNode";
import Header from "./Header";
import NoteNode from "./NoteNode";
import Sidebar from "./Sidebar";
import useFlowStore from "./flowStore";

// 自定义组件
const nodeTypes = { flowNode: FlowNode, noteNode: NoteNode };
// 流程编排面板
export default function Panne({ flow, preFlow }: { flow: WorkFlow, preFlow: string }) {
    const [reactFlowInstance, setReactFlowInstance] = useState(null);
    const { t } = useTranslation('flow')
    // 导入自适应布局
    const fitView = useFlowStore(state => state.fitView)
    const [flowKey, setFlowKey] = useState(1)
    useEffect(() => {
        if (reactFlowInstance) {
            setTimeout(() => {
                reactFlowInstance.fitView();
                setFlowKey(Date.now())
            }, 0);
        }
    }, [fitView])

    useEffect(() => {
        return () => {
            setReactFlowInstance(null) // 销毁reactflow实例
        }
    }, [])

    const { takeSnapshot } = useUndoRedo()

    const {
        reactFlowWrapper, nodes, edges, keyBoardPanneRef,
        setNodes, onNodesChange, onSelectionChange, onEdgesChange,
        onEdgeSelect, onConnect, onDragOver, onDrop, setEdges, setViewport, createNote
    } = useFlow(reactFlowInstance, flow, takeSnapshot)
    const workflowBackground = window.ThemeStyle?.bg || 'logo'

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
        <Header
            flow={flow}
            nodes={nodes}
            onTabChange={(type) => setShowApiPage('api' === type)}
            preFlow={preFlow}
            onImportFlow={(nodes, edges, viewport) => {
                setNodes(nodes)
                setEdges(edges)
                setViewport(viewport)
            }}
            onPreFlowChange={() => {
                // 返回上一步前, 更新flow数据再对比
                const { nodes } = reactFlowInstance.toObject()
                setNodes(nodes)
            }}
        ></Header>
        <div className={`flex-1 min-h-0 overflow-hidden ${showApiPage ? 'hidden' : ''} relative`}>
            <Sidebar onInitStartNode={node => {
                // start node
                const nodeId = `${node.type}_${generateUUID(5)}`;
                node.id = nodeId;
                node.name = t(`node.${node.type}.name`)
                node.description = t(`node.${node.type}.description`)
                if (!flow.nodes || flow.nodes.length === 0) {
                    setTimeout(() => {
                        setNodes([{ id: nodeId, type: 'flowNode', position: { x: window.innerWidth * 0.4, y: 20 }, data: node }]);
                    }, 500); // after init
                }
            }} />
            <main
                className="h-full flex flex-1 bg-gray-50"
                tabIndex={-1}
                ref={keyBoardPanneRef}>
                <div className="size-full" ref={reactFlowWrapper}>
                    <div className="size-full">
                        <ReactFlow
                            key={flowKey}
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
                            className={workflowBackground === 'logo' ? "flow-bg-logo" : undefined}
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
                            onNodesDelete={() => {
                                console.log('【删除节点】');
                                takeSnapshot(flow)
                            }} // 更新setEdges
                            // 自定义线组件
                            // connectionLineComponent={ConnectionLineComponent} 
                            // 校验连线合法性
                            // onReconnect={onEdgeUpdate} 
                            // onReconnectStart={onEdgeUpdateStart}
                            // onReconnectEnd={onEdgeUpdateEnd}
                            style={{
                                backgroundImage: workflowBackground === 'gradient'
                                    ? 'radial-gradient(circle at center bottom, hsl(var(--primary) / 30%) 2%, hsl(var(--primary) / 20%) 25%, hsl(var(--primary) / 5%) 60%, rgba(0, 0, 0, 0) 100%)'
                                    : undefined,
                                backgroundRepeat: 'no-repeat',
                                backgroundSize: 'cover',
                            }}
                        >
                            <Background className="dark:bg-gray-950" color='#999' variant={BackgroundVariant.Dots} />
                            <Controls position="bottom-left" onCreateNote={createNote}></Controls>
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
    const { t } = useTranslation('flow')
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
            let _nodes = []
            setNodes((x) => {
                _nodes = x
                return x
                // 触发此方法时，避免克隆节点。因为节点已经在组件内部被闭包捕获，直接更新节点会导致更新的是旧的节点，而不是最新的节点
                // return cloneDeep(x)
            });
            setEdges((eds) => {
                // 校验
                const _eds = filterUselessFlow(_nodes, eds)
                return addEdge(
                    {
                        ...params,
                        type: 'customEdge',
                        // style: { stroke: "#024de3", strokeWidth: 2 },
                        // className: 'stroke-foreground stroke-connection',
                        animated: true
                    },
                    _eds
                )
            });
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
                    const newNode = initNode(flowdata.node, nds, t)
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
            const newNode = initNode(flowdata.node, nds, t)
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
        const handleCopy = async (event) => {
            const nodeIds = event.detail;
            let nodes = _reactFlowInstance.getNodes();
            // let edges = _reactFlowInstance.getEdges();

            const newNodes = await Promise.all(nodeIds.map(async nodeId => {
                const node = nodes.find(n => n.id === nodeId);
                const position = calculatePosition(nodes, {
                    x: node.position.x + 100,
                    y: node.position.y + 100,
                })
                if (node.type === "noteNode") {
                    const newNodeId = `note_${generateUUID(5)}`
                    return {
                        id: newNodeId,
                        type: "noteNode",
                        data: {
                            ...node.data,
                            id: newNodeId
                        },
                        position,
                        selected: false
                    };
                }
                const newNodeId = `${node.data.type}_${generateUUID(5)}`
                // id替换
                const data = JSON.parse(JSON.stringify(node.data).replaceAll(nodeId, newNodeId))
                // 复制报告节点中报告模板
                await copyReportTemplate(data);
                return {
                    id: newNodeId,
                    type: "flowNode",
                    position,
                    data: {
                        ...data,
                        id: newNodeId,
                    },
                    selected: false
                };
            }));

            // 增加节点
            setNodes((nds) => {
                const _newNodes = newNodes.map(node => {
                    if (node.type === "flowNode") {
                        node.data.name = autoNodeName(nds, node.data.name)
                    }
                    return node
                });
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
                const _newNode = initNode(newNode.node, nds, t)
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


        // 删除输出节点连线
        const handleDelOutputEdge = (event) => {
            const { nodeId } = event.detail;
            setEdges((eds) => eds.filter((ns) => ns.source !== nodeId));
        }

        // 监听自定义事件
        window.addEventListener('nodeUpdate', handleNodeUpdate);
        window.addEventListener('nodeDelete', handleNodeDelete);
        window.addEventListener('nodeCopy', handleCopy);
        window.addEventListener('addNodeByHandle', handleAddNode);
        window.addEventListener('outputDelEdge', handleDelOutputEdge);

        // 在组件卸载时移除事件监听
        return () => {
            window.removeEventListener('nodeUpdate', handleNodeUpdate);
            window.addEventListener('nodeDelete', handleNodeDelete);
            window.removeEventListener('nodeCopy', handleCopy);
            window.removeEventListener('addNodeByHandle', handleAddNode);
            window.addEventListener('outputDelEdge', handleDelOutputEdge);
        };
    }, [_reactFlowInstance]);

    // 添加便签节点
    const handleAddNote = () => {
        takeSnapshot()
        const nodeId = `note_${generateUUID(5)}`
        const reactflowBounds = reactFlowWrapper.current.getBoundingClientRect();
        const pos = _reactFlowInstance.screenToFlowPosition({
            x: reactflowBounds.width * 0.2, y: reactflowBounds.height * 0.9
        });
        const position = calculatePosition(nodes, {
            x: pos.x + 50,
            y: pos.y + 50,
        })
        // 增加节点
        setNodes((nds) => {
            return nds.concat({
                id: nodeId, type: 'noteNode', position, data: {
                    id: nodeId,
                    group_params: [],
                    type: 'note',
                    value: ''
                }
            })
        });
    }
    // 选中节点
    const onSelectionChange = useCallback((data) => {
        setLastSelection(data);
    }, []);

    return {
        reactFlowWrapper, nodes, edges, keyBoardPanneRef,
        onNodesChange, onEdgesChange, onConnect, setViewport,
        onDragOver, onDrop, onSelectionChange, onEdgeSelect, setNodes, setEdges,
        createNote: handleAddNote
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
            // TODO 合并到复制节点方法
            const newNodes = newSelectNode.nodes.map(node => {
                const nodeId = `${node.data.type}_${generateUUID(5)}`
                const newNode = JSON.parse(JSON.stringify(node).replaceAll(node.id, nodeId))
                newNode.id = nodeId
                newNode.data.id = nodeId
                const newName = autoNodeName(nds, newNode.data.name)
                newNode.data.name = newName
                // 复制报告节点中报告模板
                copyReportTemplate(newNode.data)
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
