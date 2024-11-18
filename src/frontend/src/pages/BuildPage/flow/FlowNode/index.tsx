import { LoadingIcon } from '@/components/bs-icons/loading';
import { useToast } from '@/components/bs-ui/toast/use-toast';
import { WorkflowNode } from '@/types/flow';
import { Handle, NodeToolbar, Position } from '@xyflow/react';
import { useCallback, useRef, useState } from 'react';
import NodeLogo from './NodeLogo';
import NodeTabs from './NodeTabs';
import NodeToolbarComponent from './NodeToolbarComponent';
import ParameterGroup from './ParameterGroup';
import { ChevronDown } from 'lucide-react';
import EditText from './EditText';


function CustomNode({ data: node, selected, isConnectable }: { data: WorkflowNode, selected: boolean, isConnectable: boolean }) {
    const [focusUpdate, setFocusUpdate] = useState(false)
    const { message } = useToast()
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

    const paramValidateEntities = useRef({})
    const handleRun = () => {
        // vilidate node
        const errors = []
        Object.keys(paramValidateEntities.current).forEach(key => {
            const { param, validate } = paramValidateEntities.current[key]
            if (param.tab && node.tab && node.tab.value !== param.tab) return
            const msg = validate()
            msg && errors.push(msg)
        })

        if (errors.length) return message({
            description: errors,
            variant: 'warning'
        })
    }

    const [expend, setExpend] = useState(false)
    return (
        <div className={`${selected ? 'border-primary' : 'border-transparent'} border rounded-[20px]`}>
            {/* head bars */}
            <NodeToolbar align="end">
                <NodeToolbarComponent nodeId={node.id} type={node.type} onRun={handleRun}></NodeToolbarComponent>
            </NodeToolbar>

            <div
                className={`bisheng-node hover:border-primary/10 ${node.type === 'condition' ? 'w-auto min-w-80' : ''} ${selected ? 'border-primary/10' : ' border-transparent'}`}
                data-id={node.id}
            >
                {/* top */}
                <div className='bisheng-node-top flex items-center'>
                    <LoadingIcon className='size-5 text-[#B3BBCD]' />
                    <span className='text-sm text-[#B3BBCD]'>BISHENG</span>
                </div>
                {/* head */}
                <div className='bisheng-node-head'>
                    <div className='relative z-10 flex gap-2'>
                        <NodeLogo type={node.type} colorStr={node.name} />
                        <EditText >
                            <span className='truncate'>{node.name}</span>
                        </EditText>
                        {!['output', 'condition', 'end'].includes(node.type) && <ChevronDown
                            className={`absolute right-0 bisheng-label cursor-pointer ${expend && 'rotate-180'}`}
                            size={14}
                            onClick={() => setExpend(!expend)}
                        />}
                        {/* <EditTitle str={node.name} className={'text-background'} onChange={() => { }}>
                            {(val) => <p className='text-gray-50 font-bold'>{val}</p>}
                        </EditTitle> */}
                    </div>
                    <EditText type='textarea'>
                        <p className='text-xs text-muted-foreground mt-2'>{node.description}</p>
                    </EditText>
                </div>
                {/* body */}
                <div className='-nowheel bg-[#F7F8FB] pb-5 rounded-b-[20px]'>
                    <div className={expend ? `h-0 overflow-hidden` : ''}>
                        {node.tab && <NodeTabs
                            data={node.tab}
                            onChange={(val) => {
                                setCurrentTab(val)
                                node.tab.value = val
                            }} />}
                        {node.group_params.map(group =>
                            <ParameterGroup
                                nodeId={node.id}
                                key={group.name}
                                tab={currentTab}
                                cate={group}
                                onOutPutChange={handleChangeOutPut}
                                onStatusChange={((key, obj) => paramValidateEntities.current[key] = obj)}
                            />
                        )}
                    </div>
                </div>
                {/* footer */}
                {node.type !== 'start' && <Handle
                    id="left_handle"
                    type="target"
                    position={Position.Left}
                    className='bisheng-flow-handle group'
                    style={{ top: 58, left: -16 }}
                ><span></span></Handle>}
                {!['condition', 'output', 'end'].includes(node.type) && <Handle
                    id="right_handle"
                    type="source"
                    position={Position.Right}
                    className='bisheng-flow-handle group'
                    style={{ top: 58, right: -16 }}
                ><span></span></Handle>}
            </div>
        </div>
    );
}

export default CustomNode;
