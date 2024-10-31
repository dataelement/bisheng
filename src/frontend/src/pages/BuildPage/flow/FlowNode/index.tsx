import { Badge } from '@/components/bs-ui/badge';
import { Input, Textarea } from '@/components/bs-ui/input';
import EditTitle from '@/components/bs-ui/input/editTitle';
import { Label } from '@/components/bs-ui/label';
import { cn } from '@/utils';
import { House, SprayCan } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { Handle, NodeToolbar, Position } from 'reactflow';
import NodeToolbarComponent from './NodeToolbarComponent';
import ParameterGroup from './ParameterGroup';
import { WorkflowNode } from '@/types/flow';
import { Icons } from '../Sidebar';
import NodeTabs from './NodeTabs';


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

    const CompIcon = Icons[node.type] || SprayCan

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
        <div>
            {/* head bars */}
            <NodeToolbar align="end">
                <NodeToolbarComponent></NodeToolbarComponent>
            </NodeToolbar>

            <div className={cn("bisheng-node border-2", selected ? "active" : "")}>
                {/* head */}
                <div className='p-4 bisheng-node-head'>
                    <div className='relative z-10 flex gap-2'>
                        <CompIcon className='text-blue-700' />
                        <EditTitle str={node.name} className={'text-background'} onChange={() => { }}>
                            {(val) => <p className='text-gray-50 font-bold'>{val}</p>}
                        </EditTitle>
                    </div>
                </div>
                <p className='text-xs p-2 bg-background text-muted-foreground'>{node.description}</p>
                {/* body */}

                <div className='-nowheel'>
                    {node.tab && <NodeTabs data={node.tab} onChange={(val) => {
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
                    style={{ left: -8 }}
                />}
                {!['condition', 'output', 'end'].includes(node.type) && <Handle
                    id="right_handle"
                    type="source"
                    position={Position.Right}
                    className='bisheng-flow-handle'
                    style={{ right: -8 }}
                />}
            </div>
        </div>
    );
}

export default CustomNode;
