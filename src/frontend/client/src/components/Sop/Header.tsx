import { FileText, MessageCircleMoreIcon } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Select, SelectContent, SelectItem, SelectTrigger } from '~/components/ui/Select';
import { Button, Skeleton } from '../ui';
import { Popover, PopoverContent, PopoverTrigger } from '../ui/Popover';
import { useLinsightManager } from '~/hooks/useLinsightManager';

export const Header = ({ isLoading, sesstionId, versionId, versions }) => {
    const [open2, setOpen2] = useState(false);
    const { getLinsight } = useLinsightManager()
    const linsight = useMemo(() => {
        return getLinsight(sesstionId)
    }, [getLinsight, sesstionId])

    // console.log('linsight :>> ', linsight);

    return (
        <div className="flex items-center justify-between p-4">
            {isLoading ?
                <Skeleton className="h-7 w-[250px] rounded-lg bg-gray-100 opacity-100" />
                : <div className="flex items-center gap-3">
                    <FileText className="size-4" />
                    <span className="text-base font-medium text-gray-900">
                        {linsight?.title}
                    </span>
                </div>
            }

            <div className="flex items-center gap-3">
                <Popover open={open2}>
                    <PopoverTrigger asChild>
                        <Button
                            variant="outline"
                            size="sm"
                            className="h-7 px-3 rounded-lg shadow-sm focus-visible:outline-0"
                            onMouseEnter={() => setOpen2(true)}
                            onMouseLeave={() => setOpen2(false)}
                        >
                            <MessageCircleMoreIcon className="size-4" />
                            <span className="text-xs">任务描述</span>
                        </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-96 border border-[#BCD2FF] rounded-xl bg-[#E5EEFF]">
                        <p className='text-sm font-bold mb-2'>任务描述</p>
                        <p className='text-sm'>{linsight?.question}</p>
                    </PopoverContent>
                </Popover>

                {
                    versions.length > 0 && <Select onValueChange={() => console.log('切换版本 :>> ')}>
                        <SelectTrigger className="h-7 rounded-lg px-3 border bg-white hover:bg-gray-50 data-[state=open]:border-blue-500">
                            <div className="flex items-center gap-2">
                                <span className="text-xs font-normal text-gray-600">{versions.find(task => task.id === versionId)?.name}</span>
                            </div>
                        </SelectTrigger>
                        <SelectContent className="bg-white rounded-lg p-2 w-52 shadow-md">
                            {
                                versions.map(task => <SelectItem key={task.id} value="option1" className="text-xs px-3 py-2 hover:bg-gray-50">
                                    任务版本 {task.name}
                                </SelectItem>)
                            }
                        </SelectContent>
                    </Select>
                }
            </div>
        </div>
    );
};