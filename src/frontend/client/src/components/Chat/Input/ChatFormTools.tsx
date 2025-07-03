import { FileText, GlobeIcon, Settings2Icon, Wrench } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Switch } from '~/components/ui';
import { Select, SelectContent, SelectTrigger } from '~/components/ui/Select';
import {
    BsConfig
} from '~/data-provider/data-provider/src';
import { cn } from '~/utils';

// 工具
export const ChatToolDown = ({ linsi, config, searchType, setSearchType, disabled }
    : { linsi: boolean, config?: BsConfig, searchType: string, setSearchType: (type: string) => void, disabled: boolean }) => {

    if (linsi) return <LinsiTools />

    return <Select disabled={disabled}>
        <SelectTrigger className="h-7 rounded-full px-2 bg-white dark:bg-transparent data-[state=open]:border-blue-500">
            <div className={cn('flex gap-2', searchType && 'text-blue-600')}>
                <Settings2Icon size="16" />
                <span className="text-xs font-normal">工具</span>
            </div>
        </SelectTrigger>
        <SelectContent className='bg-white rounded-xl p-2 w-52'>
            {
                config?.webSearch.enabled && <div className='flex justify-between mb-2'>
                    <div className='flex gap-2 items-center'>
                        <GlobeIcon className='' size="16" />
                        <span className="text-xs font-normal">联网搜索</span>
                    </div>
                    <Switch className='data-[state=checked]:bg-blue-600'
                        disabled={disabled}
                        checked={searchType === 'netSearch'}
                        onCheckedChange={val => {
                            if (searchType === 'netSearch') {
                                setSearchType('');
                            } else {
                                setSearchType('netSearch');
                            }
                        }}
                    ></Switch>
                </div>
            }
            {
                config?.knowledgeBase.enabled && <div className='flex justify-between'>
                    <div className='flex gap-2 items-center'>
                        <FileText size="16" />
                        <span className="text-xs font-normal">个人知识库</span>
                    </div>
                    <Switch className='data-[state=checked]:bg-blue-600'
                        disabled={disabled}
                        checked={searchType === 'knowledgeSearch'}
                        onCheckedChange={val => {
                            if (searchType === 'knowledgeSearch') {
                                setSearchType('');
                            } else {
                                setSearchType('knowledgeSearch');
                            }
                        }}
                    ></Switch>
                </div>
            }
        </SelectContent>
    </Select>
}


const LinsiTools = () => {

    const [tools, setTools] = useState([
        {
            id: 'knowledge',
            name: '个人知识库',
            icon: <FileText size="16" />,
            checked: true
        }, {
            id: 'search',
            name: '联网搜索',
            icon: <GlobeIcon size="16" />,
            checked: true
        }, {
            id: 'f23',
            name: '其他工具',
            icon: <Wrench size="16" />,
            checked: true
        }, {
            id: 'sd3',
            name: '一级工具名',
            icon: <Wrench size="16" />,
            checked: true
        }
    ])

    const active = useMemo(() => tools.some(tool => tool.checked), [tools])

    return <Select >
        <SelectTrigger className="h-7 rounded-full px-2 bg-white dark:bg-transparent data-[state=open]:border-blue-500">
            <div className={cn('flex gap-2', active && 'text-blue-600')}>
                <Settings2Icon size="16" />
                <span className="text-xs font-normal">工具</span>
            </div>
        </SelectTrigger>
        <SelectContent className='bg-white rounded-xl p-2 w-52'>
            {tools.map(tool => {
                return <div key={tool.name} className='flex justify-between mb-2'>
                    <div className='flex gap-2 items-center'>
                        {tool.icon}
                        <span className="text-xs font-normal">{tool.name}</span>
                    </div>
                    <Switch className='data-[state=checked]:bg-blue-600'
                        checked={tool.checked}
                        onCheckedChange={val =>
                            setTools(tools.map(t => t.id === tool.id ? { ...t, checked: val } : t))
                        }
                    ></Switch>
                </div>
            })}
        </SelectContent>
    </Select>
}