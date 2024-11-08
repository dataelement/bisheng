import { LoadingIcon } from '@/components/bs-icons/loading';
import { WorkflowNode } from '@/types/flow';
import { Handle, NodeToolbar, Position } from '@xyflow/react';
import { useCallback, useEffect, useState } from 'react';
import NodeLogo from './NodeLogo';
import NodeTabs from './NodeTabs';
import NodeToolbarComponent from './NodeToolbarComponent';
import ParameterGroup from './ParameterGroup';


function CustomNode({ data: node, selected, isConnectable }: { data: WorkflowNode, selected: boolean, isConnectable: boolean }) {
    const [focusUpdate, setFocusUpdate] = useState(false)
    const onChange = useCallback((evt) => {
        console.log(evt.target.value);
    }, []);
    const [currentTab, setCurrentTab] = useState<undefined | string>(node.tab && node.tab.value)

    const handleUpdate = () => {
        // 创建并触发自定义事件，传递需要更新的节点 id 和数据
        const event = new CustomEvent('nodeUpdate', {
            detail: {
                nodeId: node.id,
                newData: { label: `Updated at ${new Date().toLocaleTimeString()}` }
            }
        });
        window.dispatchEvent(event);
    };

    useEffect(() => {
        window.node = node
    }, [])

    // 部分节点动态修改输出项内容
    const handleChangeOutPut = (key: string, value: any) => {
        node.group_params.some(group => {
            return group.params.some(param => {
                if (param.key === key) {
                    param.value = value.map(item => ({
                        key: 'output_' + item.key,
                        label: 'output_' + item.label
                    }))
                    return true
                }
            })
        })
        setFocusUpdate(!focusUpdate) // render
        console.log('node :>> ', key, value, node);
    }

    return (
        <div className={`${selected ? 'border-primary' : 'border-transparent'} border rounded-[20px] p-[1px]`}>
            {/* head bars */}
            <NodeToolbar align="end">
                <NodeToolbarComponent nodeId={node.id} type={node.type}></NodeToolbarComponent>
            </NodeToolbar>

            <div className={`bisheng-node ${node.type === 'condition' ? 'w-auto min-w-80' : ''}`} data-id={node.id}>
                {/* top */}
                <div className='bisheng-node-top flex items-center'>
                    <LoadingIcon className='size-5 text-[#B3BBCD]' />
                    <span className='text-sm text-[#B3BBCD]'>BISHENG</span>
                </div>
                {/* head */}
                <div className='bisheng-node-head'>
                    <div className='relative z-10 flex gap-2'>
                        <NodeLogo type={node.type} />
                        <span>{node.name}</span>
                        {/* <EditTitle str={node.name} className={'text-background'} onChange={() => { }}>
                            {(val) => <p className='text-gray-50 font-bold'>{val}</p>}
                        </EditTitle> */}
                    </div>
                    <p className='text-xs text-muted-foreground mt-2'>{node.description}</p>
                </div>
                {/* body */}
                <div className='-nowheel'>
                    {node.tab && <NodeTabs
                        data={node.tab}
                        onChange={(val) => {
                            setCurrentTab(val)
                            node.tab.value = val
                        }} />}
                    {node.group_params.map(group =>
                        <ParameterGroup nodeId={node.id} key={group.name} tab={currentTab} cate={group} onOutPutChange={handleChangeOutPut} />
                    )}
                </div>
                {/* footer */}
                {node.type !== 'start' && <Handle
                    id="left_handle"
                    type="target"
                    position={Position.Left}
                    className='bisheng-flow-handle'
                    style={{ left: -16 }}
                />}
                {!['condition', 'output', 'end'].includes(node.type) && <Handle
                    id="right_handle"
                    type="source"
                    position={Position.Right}
                    className='bisheng-flow-handle'
                    style={{ right: -16 }}
                />}
            </div>
        </div>
    );
}

export default CustomNode;
