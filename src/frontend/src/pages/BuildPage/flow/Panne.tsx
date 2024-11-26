import { generateUUID } from "@/components/bs-ui/utils";
import { WorkFlow, WorkflowNode } from "@/types/flow";
import { useCopyPaste, useUndoRedo } from "@/util/hook";
import { Background, BackgroundVariant, Connection, Controls, ReactFlow, addEdge, applyEdgeChanges, applyNodeChanges, useReactFlow } from '@xyflow/react';
import '@xyflow/react/dist/base.css';
import '@xyflow/react/dist/style.css';
import cloneDeep from "lodash-es/cloneDeep";
import { useCallback, useEffect, useRef, useState } from "react";
import CustomEdge from "./FlowEdge";
import FlowNode from "./FlowNode";
import Header from "./Header";
import Sidebar from "./Sidebar";
import { autoNodeName, initNode } from "@/util/flowUtils";

// 自定义组件
const nodeTypes = { flowNode: FlowNode };
// 流程编排面板
export default function Panne({ flow }: { flow: WorkFlow }) {
    const [reactFlowInstance, setReactFlowInstance] = useState(null);
    useEffect(() => {
        return () => {
            setReactFlowInstance(null) // 销毁reactflow实例
        }
    }, [])

    const { reactFlowWrapper, nodes, edges, keyBoardPanneRef,
        setNodes, onNodesChange, onSelectionChange, onEdgesChange, onEdgeSelect, onConnect, onDragOver, onDrop } = useFlow(reactFlowInstance, flow)

    useUndoRedo(nodes,
        (data) => {
            console.log('undo :>> ', data);
        }, (data) => {
            console.log('redo :>> ', data);
        })
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

    const [showApiPage, setShowApiPage] = useState(false)
    return <div className="flex flex-col h-full overflow-hidden">
        <Header flow={flow} onTabChange={(type) => setShowApiPage('api' === type)}></Header>
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
                            onPaneClick={() => { setDropdownOpenEdgeId(null) }}
                            edgeTypes={{
                                customEdge: (edgeProps) => (
                                    <CustomEdge
                                        {...edgeProps}
                                        isDropdownOpen={dropdownOpenEdgeId === edgeProps.id}
                                        onButtonClick={handleButtonClick}
                                        onOptionSelect={() => { onEdgeSelect(); setDropdownOpenEdgeId(null) }}
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
                            // 自定义线组件
                            // connectionLineComponent={ConnectionLineComponent} 
                            // 校验连线合法性
                            // onReconnect={onEdgeUpdate} 
                            // onReconnectStart={onEdgeUpdateStart}
                            // onReconnectEnd={onEdgeUpdateEnd}
                            // onEdgesDelete={onEdgesDelete}

                            // onNodesDelete={onDelete} // 更新setEdges
                            // onNodeDragStart={onNodeDragStart} // 快照
                            // onSelectionDragStart={onSelectionDragStart} // 快照
                            // 框选 (group)
                            // onSelectionStart={(e) => { e.preventDefault(); setSelectionEnded(false) }}
                            // onSelectionEnd={() => setSelectionEnded(true)}
                            style={{
                                backgroundImage: window.ThemeStyle.bg === 'gradient'
                                    && 'radial-gradient(circle at center bottom, rgba(2, 77, 227, 0.3) 2%, rgba(2, 77, 227, 0.2) 25%, rgba(2, 77, 227, 0.05) 60%, rgba(255, 255, 255, 0) 100%)',
                                backgroundRepeat: 'no-repeat',
                                backgroundSize: 'cover',
                            }}
                        >
                            <Background color='#999' variant={BackgroundVariant.Dots} />
                            <Controls></Controls>
                        </ReactFlow>
                    </div>
                </div>
            </main>
        </div>
        <div className={`flex flex-1 min-h-0 overflow-hidden ${showApiPage ? '' : 'hidden'}`}>
            {/* <ApiMainPage type={'flow'} /> */}
            come sun~
        </div>
    </div>
};


const useFlow = (_reactFlowInstance, data) => {

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
    const { keyBoardPanneRef, setLastSelection } = useKeyBoard(reactFlowWrapper, setNodes)

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
            console.log('conect :>> ', params);
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
        [setEdges, setNodes]
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
                const reactflowBounds = reactFlowWrapper.current.getBoundingClientRect();
                let data: { type: string; node?: WorkflowNode } = JSON.parse(
                    event.dataTransfer.getData("flownodedata")
                );

                const position = _reactFlowInstance.screenToFlowPosition({
                    x: event.clientX - reactflowBounds.left,
                    y: event.clientY - reactflowBounds.top,
                });
                console.log('object :>> ', position, data);

                const nodeId = `${data.node.type}_${generateUUID(5)}`
                data.node.id = nodeId
                // 增加节点
                setNodes((nds) => {
                    const newName = autoNodeName(nds, data.node.name)
                    const newNode = initNode(data.node)
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
        [setNodes, _reactFlowInstance]
    );

    const onEdgeSelect = useCallback(() => {
        const reactflowBounds = reactFlowWrapper.current.getBoundingClientRect();
        const position = _reactFlowInstance.screenToFlowPosition({
            x: 1 - reactflowBounds.left,
            y: 2 - reactflowBounds.top,
        });
        // setNodes((nds) => nds.concat(
        //     { id: 'c', type: 'flowNode', position, data: { value: 'Node B' } }
        // ));
    }, [setNodes, _reactFlowInstance])

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

        // 监听自定义事件
        window.addEventListener('nodeUpdate', handleNodeUpdate);
        window.addEventListener('nodeDelete', handleNodeDelete);
        window.addEventListener('nodeCopy', handleCopy);


        // 在组件卸载时移除事件监听
        return () => {
            window.removeEventListener('nodeUpdate', handleNodeUpdate);
            window.addEventListener('nodeDelete', handleNodeDelete);
            window.removeEventListener('nodeCopy', handleCopy);
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
const useKeyBoard = (reactFlowWrapper, setNodes) => {
    const keyBoardPanneRef = useRef<HTMLDivElement>(null); // 绑定快捷键
    const [lastSelection, setLastSelection] = useState(null);
    useCopyPaste(keyBoardPanneRef.current, lastSelection, (newSelection, position) => {
        let bounds = reactFlowWrapper.current.getBoundingClientRect();
        setNodes((nds) => nds.concat(
            {
                id: 'd', type: 'flowNode', position: {
                    x: position.x - bounds.left,
                    y: position.y - bounds.top,
                }, data: { value: 'Node 2' }
            }
        ))
    }, [setNodes])

    return { keyBoardPanneRef, setLastSelection }
}

// TODO 离开页面保存提示