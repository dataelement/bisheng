import { generateUUID } from "@/components/bs-ui/utils";
import { WorkFlow, WorkflowNode } from "@/types/flow";
import { useCopyPaste, useUndoRedo } from "@/util/hook";
import cloneDeep from "lodash-es/cloneDeep";
import { useCallback, useEffect, useRef, useState } from "react";
import ReactFlow, { Background, BackgroundVariant, Connection, Controls, addEdge, applyEdgeChanges, applyNodeChanges } from 'reactflow';
import CustomEdge from "./FlowEdge";
import FlowNode from "./FlowNode";
import Header from "./Header";
import Sidebar from "./Sidebar";

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

    return <div className="flex flex-col h-full overflow-hidden">
        <Header flow={flow}></Header>
        <div className="flex-1 min-h-0 overflow-hidden relative">
            <Sidebar onInitStartNode={node => {
                // start node
                const nodeId = `${node.type}_${generateUUID(5)}`;
                node.id = nodeId;
                (!flow.nodes || flow.nodes.length === 0) && setNodes([{ id: nodeId, type: 'flowNode', position: { x: window.innerWidth * 0.4, y: 20 }, data: node }])
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
                            className="theme-attribution"
                            onDragOver={onDragOver}
                            onDrop={onDrop}
                            onSelectionChange={onSelectionChange}
                            onNodesDelete={() => {
                                console.log('111 :>> ', 111);
                                return false
                            }}
                        // 自定义线组件
                        // connectionLineComponent={ConnectionLineComponent} 
                        // 校验连线合法性
                        // onEdgeUpdate={onEdgeUpdate} 
                        // onEdgeUpdateStart={onEdgeUpdateStart}
                        // onEdgeUpdateEnd={onEdgeUpdateEnd}
                        // onEdgesDelete={onEdgesDelete}

                        // onNodesDelete={onDelete} // 更新setEdges
                        // onNodeDragStart={onNodeDragStart} // 快照
                        // onSelectionDragStart={onSelectionDragStart} // 快照
                        // 框选 (group)
                        // onSelectionStart={(e) => { e.preventDefault(); setSelectionEnded(false) }}
                        // onSelectionEnd={() => setSelectionEnded(true)}
                        // style={{ backgroundImage: 'url(/test.svg)' }}
                        >
                            <Background className="bg-background" color='#999' variant={BackgroundVariant.Dots} />
                            <Controls></Controls>
                        </ReactFlow>
                    </div>
                </div>
            </main>
        </div>
    </div>
};


const useFlow = (_reactFlowInstance, data) => {

    const reactFlowWrapper = useRef(null);

    const [nodes, setNodes] = useState(data.nodes);
    const [edges, setEdges] = useState(data.edges);
    console.log('nodes edges:>> ', nodes, edges);

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
                        style: { stroke: "#024de3", strokeWidth: 2 },
                        className: 'stroke-foreground stroke-connection',
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

                const position = _reactFlowInstance.project({
                    x: event.clientX - reactflowBounds.left,
                    y: event.clientY - reactflowBounds.top,
                });
                console.log('object :>> ', position, data);

                const nodeId = `${data.node.type}_${generateUUID(5)}`
                data.node.id = nodeId
                setNodes((nds) => nds.concat(
                    { id: nodeId, type: 'flowNode', position, data: data.node }
                ));
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
        const position = _reactFlowInstance.project({
            x: 1 - reactflowBounds.left,
            y: 2 - reactflowBounds.top,
        });
        setNodes((nds) => nds.concat(
            { id: 'c', type: 'flowNode', position, data: { value: 'Node B' } }
        ));
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

        // 监听自定义事件
        window.addEventListener('nodeUpdate', handleNodeUpdate);

        // 在组件卸载时移除事件监听
        return () => {
            window.removeEventListener('nodeUpdate', handleNodeUpdate);
        };
    }, []);

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