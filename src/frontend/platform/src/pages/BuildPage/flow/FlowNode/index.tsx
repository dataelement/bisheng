import { LoadingIcon } from '@/components/bs-icons/loading';
import { Card, CardContent } from '@/components/bs-ui/card';
import { useToast } from '@/components/bs-ui/toast/use-toast';
import { cname } from '@/components/bs-ui/utils';
import { WorkflowNode } from '@/types/flow';
import { Handle, NodeToolbar, Position } from '@xyflow/react';
import { ChevronDown } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Sidebar from '../Sidebar';
import EditText from './EditText';
import NodeLogo from './NodeLogo';
import NodeTabs from './NodeTabs';
import NodeToolbarComponent from './NodeToolbarComponent';
import ParameterGroup from './ParameterGroup';
import RunLog from './RunLog';
import { RunTest } from './RunTest';
import { useUpdateVariableState } from './flowNodeStore';
import { useTranslation } from 'react-i18next';
import ParameterSubGroup from './ParameterSubGroup';

export const CustomHandle = ({ id = '', node, isLeft = false, className = '' }) => {
    const [openLeft, setOpenLeft] = useState(false);
    const [openRight, setOpenRight] = useState(false);
    const posRef = useRef({ x: 0, y: 0 });

    useEffect(() => {
        const handleAddLine = () => {
            setOpenLeft(false);
            setOpenRight(false);
        };

        window.addEventListener("closeHandleMenu", handleAddLine);
        return () => {
            window.removeEventListener("closeHandleMenu", handleAddLine);
        };
    }, []);

    const handleOptionClick = (newNode) => {
        const addNodeEvent = new CustomEvent("addNodeByHandle", {
            detail: {
                id,
                targetNode: node,
                newNode: newNode,
                isLeft: isLeft,
                position: posRef.current
            }
        });
        window.dispatchEvent(addNodeEvent);
    };

    if (isLeft) {
        return <div className={cname('absolute top-[58px] -left-[16px]', className)}>
            <Handle
                id={id || "left_handle"}
                type="target"
                position={Position.Left}
                className='bisheng-flow-handle group'
                onClick={(e) => {
                    posRef.current = { x: e.clientX, y: e.clientY }
                    setOpenLeft(true)
                }}
            ><span></span></Handle>
            {
                openLeft && <Card
                    className="absolute top-4 translate-x-[-50%] bg-transparent hover:shadow-none hover:border-transparent"
                    style={{ zIndex: 1001 }}
                >
                    <CardContent className="min-w-56 pointer-events-auto px-0">
                        <Sidebar
                            dropdown
                            disabledNodes={['end']}
                            onClick={handleOptionClick}
                        ></Sidebar>
                    </CardContent>
                </Card>
            }
        </div>
    }

    return <div className={cname('absolute top-[58px] right-[-16px]', className)}>
        <Handle
            id={id || "right_handle"}
            type="source"
            position={Position.Right}
            className='bisheng-flow-handle group'
            onClick={(e) => {
                posRef.current = { x: e.clientX, y: e.clientY }
                setOpenRight(true)
            }}
        ><span></span></Handle>
        {
            openRight && <Card
                className="absolute top-4 translate-x-[-50%] bg-transparent hover:shadow-none hover:border-transparent"
                style={{ zIndex: 1001 }}
            >
                <CardContent className="min-w-56 pointer-events-auto px-0">
                    <Sidebar
                        dropdown
                        onClick={handleOptionClick}
                    ></Sidebar>
                </CardContent>
            </Card>
        }
    </div>
}

function CustomNode({ data: node, selected, isConnectable }: { data: WorkflowNode, selected: boolean, isConnectable: boolean }) {
    const [focusUpdate, setFocusUpdate] = useState(false)
    const runRef = useRef(null)
    const { message } = useToast()
    const [currentTab, setCurrentTab] = useState<undefined | string>(node.tab && node.tab.value)
    const { t } = useTranslation('flow')

    // 检查知识库检索设置
    const hasKnowledgeSearchEnabled = useMemo(() => {
        const knowledgeGroup = node.group_params.find(group => group.name === '知识库检索设置');

        if (knowledgeGroup && knowledgeGroup.params) {
            const thirdItem = knowledgeGroup.params[2]; // 第三项（索引为2）

            return thirdItem.value && thirdItem.value?.conditions?.length > 0 && thirdItem.value?.enabled;
        }
        return false;
    }, [
        node.group_params.find(group => group.name === '知识库检索设置')?.params?.[2]?.value?.conditions?.length,
        node.group_params.find(group => group.name === '知识库检索设置')?.params?.[2]?.value?.enabled
    ]);

    // 动态计算节点宽度类名
    const nodeWidthClass = useMemo(() => {
        const baseClasses = ['condition'];

        if (hasKnowledgeSearchEnabled) {
            baseClasses.push('rag');
            baseClasses.push('knowledge_retriever');
        }
        return baseClasses.includes(node.type) ? 'w-auto min-w-80' : '';
    }, [node.type, hasKnowledgeSearchEnabled]);

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
                    const prefix = key.split('_')[0]
                    const values = Array.isArray(value) ? value : [value];
                    param.value = values.map(item => ({
                        key: `${prefix}_${item.key}`,
                        label: `${prefix}_${item.label}`
                    }))
                    return true
                }
            })
        })
        setFocusUpdate(!focusUpdate) // render
    }

    const [nodeError, setNodeError] = useBorderColor(node)
    const { paramValidateEntities, varValidateEntities, validateAll } = useEventMaster(node, setNodeError)
    const handleRun = async () => {
        // vilidate node
        const errors = await validateAll({ tmp: true })

        if (errors.length) return message({
            description: errors,
            variant: 'warning'
        })

        runRef.current.run(node)
    }

    // 直接使用函数获取知识库ID，不依赖useMemo
    const getSelectedKnowledgeIds = () => {
        if (!node) {
            return [];
        }

        const knowledgeParam = node.group_params
            .flatMap(group => group.params)
            .find(param => param.type === "knowledge_select_multi");

        if (knowledgeParam && knowledgeParam.value && Array.isArray(knowledgeParam.value.value)) {
            const ids = knowledgeParam.value.value.map(kb => String(kb.key));
            return ids;
        }
        return [];
    }

    // update system prompt
    const hackCountRef = useRef(0)
    const handleAddSysPrompt = (type: 'knowledge' | 'sql') => {
        node.group_params.forEach(group => {
            if (group.params && Array.isArray(group.params)) {

                const targetParam = group.params.find(p => p.key === 'system_prompt');

                if (targetParam) {
                    let currentValue = targetParam.value || "";
                    const map = {
                        'knowledge': t('kbQueryToolIntro'),
                        'sql': t('sqlAgentToolIntro')
                    }
                    const searchStr = map[type]
                    if (!currentValue.includes(searchStr)) {
                        hackCountRef.current++
                        const hackSpace = hackCountRef.current % 2 === 0 ? ' ' : '' // Avoid React's refresh mechanism 
                        targetParam.value = currentValue === '\n' ? searchStr : `${currentValue}\n${searchStr}${hackSpace}`;
                    }
                }
            }
        });

        setTimeout(() => {
            setFocusUpdate(!focusUpdate) // render
        }, 100);
    }

    const [expend, setExpend] = useState(node.expand === undefined ? true : node.expand)

    const { isVisible, handleMouseEnter, handleMouseLeave } = useHoverToolbar();

    const [_, setUpdateVariable] = useUpdateVariableState()

    return (
        <div
            onMouseEnter={handleMouseEnter}
            onMouseLeave={handleMouseLeave}
            className={`${selected ? 'border-primary' : 'border-transparent'} border rounded-[25px]`}>
            {/* head bars */}
            <NodeToolbar isVisible align="end" className={`${isVisible ? '' : 'hidden'}`} >
                <NodeToolbarComponent nodeId={node.id} type={node.type} onRun={handleRun}></NodeToolbarComponent>
            </NodeToolbar>

            <div
                className={cname(`bisheng-node hover:border-primary/10 max-w-[35rem] ${nodeWidthClass} ${selected ? 'border-primary/10' : ' border-transparent'}`, nodeError && 'border-red-500')}
                data-id={node.id}
            >
                {/* top */}
                <RunLog node={node}>
                    <div className='bisheng-node-top flex items-center'>
                        {t('bisheng', { ns: 'bs' }) === 'BISHENG' && <LoadingIcon className='size-5 text-[#B3BBCD]' />}
                        <span className='node-face text-sm text-[#B3BBCD]'>{t('bisheng', { ns: 'bs' })}</span>
                    </div>
                </RunLog>

                {/* head */}
                <div className='bisheng-node-head'>
                    <div className='relative z-10 flex gap-2'>
                        <NodeLogo type={node.type} colorStr={node.name} />
                        <div className='flex-1 max-w-60'>
                            <EditText
                                className='nodrag'
                                reDefaultValue
                                defaultValue={node.name}
                                maxLength={50}
                                disable={['start', 'end'].includes(node.type)}
                                onChange={(val) => {
                                    node.name = val;
                                    setUpdateVariable({
                                        action: 'u',
                                        node: {
                                            id: node.id,
                                            name: node.name,
                                        },
                                        question: null
                                    })
                                    setFocusUpdate(!focusUpdate)
                                }}>
                                <span className='truncate block min-h-4'>{node.name}</span>
                            </EditText>
                        </div>
                        {!['output', 'condition', 'end'].includes(node.type) && <div
                            className='absolute -right-1 -top-1 cursor-pointer p-2'
                            onClick={() => {
                                setExpend(!expend)
                                node.expand = !expend
                            }}>
                            <ChevronDown
                                className={`bisheng-label ${expend && 'rotate-180'}`}
                                size={16}
                            /></div>}
                    </div>
                    <EditText
                        className='nodrag mt-2 text-xs text-muted-foreground'
                        type='textarea'
                        maxLength={200}
                        disable={['start', 'end'].includes(node.type)}
                        defaultValue={node.description}
                        onChange={(val) => {
                            node.description = val;
                            setFocusUpdate(!focusUpdate)
                        }}>
                        <p className='text-xs text-muted-foreground mt-2 min-h-4'>{node.description}</p>
                    </EditText>
                </div>
                {/* body */}
                <div className='-nowheel bg-[#F7F8FB] dark:bg-background pb-5 rounded-b-[20px]'>
                    <div className={expend || ['output', 'condition', 'end'].includes(node.type) ? `` : 'h-0 overflow-hidden'}>
                        {node.tab && <NodeTabs
                            data={node}
                            onChange={(val) => {
                                setCurrentTab(val)
                                node.tab.value = val
                                // 特殊逻辑
                                handleChangeOutPut('output', [])
                                node.group_params.some(group => {
                                    return group.params.some(param => {
                                        if (param.key === "batch_variable") {
                                            param.value = []
                                            return true
                                        }
                                    })
                                })
                            }} />}
                        {node.group_params.map(group => group.groupKey ?
                            <ParameterSubGroup
                                key={group.groupKey}
                                nodeId={node.id}
                                node={node}
                                cate={group}
                                onStatusChange={((key, obj) => paramValidateEntities.current[key] = obj)}
                                onVarEvent={((key, obj) => varValidateEntities.current[key] = obj)}
                                tab={currentTab}
                            />
                            : <ParameterGroup
                                nodeId={node.id}
                                key={group.name}
                                tab={currentTab}
                                node={node}
                                cate={group}
                                onOutPutChange={handleChangeOutPut}
                                onAddSysPrompt={handleAddSysPrompt}
                                onFouceUpdate={() => setFocusUpdate(!focusUpdate)}
                                onStatusChange={((key, obj) => paramValidateEntities.current[key] = obj)}
                                onVarEvent={((key, obj) => varValidateEntities.current[key] = obj)}
                                selectedKnowledgeIds={getSelectedKnowledgeIds}
                            />
                        )}
                    </div>
                </div>
                {/* footer */}
                {
                    node.type !== 'start' && <CustomHandle isLeft node={node} />
                }
                {
                    !['condition', 'output', 'end'].includes(node.type) && <CustomHandle node={node} />
                }
            </div>

            <RunTest ref={runRef} />
        </div>
    );
}

export default CustomNode;


const useEventMaster = (node, setNodeError) => {
    const paramValidateEntities = useRef({})
    const varValidateEntities = useRef({})
    const { t } = useTranslation('flow')

    const validateParams = (noTemporaryFile) => {
        const errors = []
        Object.keys(paramValidateEntities.current).forEach(key => {
            const { param, validate } = paramValidateEntities.current[key]
            if (param.tab && node.tab && node.tab.value !== param.tab) return
            const msg = validate()
            if (noTemporaryFile && msg === 'input_file') {
                errors.push(t('tmpKnowledgeBaseNotSupportSingleNodeDebug'));
            } else {
                msg && msg !== 'input_file' && errors.push(msg)
            }
        })
        return errors
    }

    const validateAll = async (config) => {
        // item
        const errors = validateParams(false);

        // var
        const promises = Object.keys(varValidateEntities.current).map(async (key) => {
            const { param, validate } = varValidateEntities.current[key];

            // 如果 param.tab 存在且不匹配，则跳过当前项
            if (param.tab && node.tab && node.tab.value !== param.tab) return;

            const msg = await validate(config); // 获取验证结果
            if (msg) {
                Array.isArray(msg) ? errors.push(...msg) : errors.push(msg);
            }
        });

        await Promise.all(promises);

        // 如果有错误，设置错误状态
        if (errors.length > 0) setNodeError(true);

        return errors;
    }

    // 控制权交出
    useEffect(() => {
        const customEvent = new CustomEvent('node_event', {
            detail: {
                action: 'update',
                id: node.id,
                validate: validateAll,
                // log: {
                //     setData: (status, data) => { },
                //     close: () => { }
                // }
            }
        });
        window.dispatchEvent(customEvent);

        return () => {
            const customEvent = new CustomEvent('node_event', {
                detail: {
                    action: 'remove',
                    id: node.id
                }
            });
            // window.dispatchEvent(customEvent);
        }
    }, [node])

    return {
        validateAll,
        paramValidateEntities,
        varValidateEntities
    }
}

const useBorderColor = (node) => {
    const [error, setError] = useState(false)
    useEffect(() => {
        const onNodeEvent = (e) => {
            const { nodeIds } = e.detail
            setError(nodeIds.includes(node.id))
        }
        window.addEventListener('nodeErrorBorderEvent', onNodeEvent)
        return () => {
            window.removeEventListener('nodeErrorBorderEvent', onNodeEvent)
        }
    }, [])

    return [error, setError]
}


export const useHoverToolbar = () => {
    const [isVisible, setIsVisible] = useState(false);
    const timeoutRef = useRef(null);

    const handleMouseEnter = useCallback(() => {
        // 清除隐藏的延时
        if (timeoutRef.current) {
            clearTimeout(timeoutRef.current);
            timeoutRef.current = null;
        }
        setIsVisible(true);
    }, []);

    const handleMouseLeave = useCallback(() => {
        // 延迟隐藏
        timeoutRef.current = setTimeout(() => {
            setIsVisible(false);
        }, 200); // 延迟200ms
    }, []);

    return { isVisible, handleMouseEnter, handleMouseLeave };
};