import { FileText, MessageCircleMoreIcon } from 'lucide-react';
import { useMemo } from 'react';
import { useParams } from 'react-router-dom';
import { Select, SelectContent, SelectItem, SelectTrigger } from '~/components/ui/Select';
import { useConversationsInfiniteQuery } from '~/data-provider';
import { useLocalize } from '~/hooks';
import { useLinsightManager } from '~/hooks/useLinsightManager';
import { Button, Skeleton } from '../ui';
import { Popover, PopoverContent, PopoverTrigger } from '../ui/Popover';
import { getFileExtension } from '~/utils';
import FileIcon from '../ui/icon/File';

export const Header = ({ isLoading, setVersionId, versionId, versions }) => {
    const { getLinsight } = useLinsightManager()
    const localize = useLocalize()
    const linsight = useMemo(() => {
        return getLinsight(versionId)
    }, [getLinsight, versionId])

    console.log('linsight :>> ', linsight);
    const title = useCurrentTitle()

    return (
        <div className="flex items-center justify-between p-4">
            {isLoading ?
                <Skeleton className="h-7 w-[250px] rounded-lg bg-gray-100 opacity-100" />
                : <div className="flex items-center gap-3">
                    <FileText className="size-4" />
                    <span className="text-base font-medium text-gray-900">
                        {title || linsight?.title}
                    </span>
                </div>
            }

            <div className="flex items-center gap-3">
                <Popover>
                    <PopoverTrigger asChild>
                        <Button
                            variant="outline"
                            size="sm"
                            className="h-7 px-3 rounded-lg shadow-sm focus-visible:outline-0"
                        >
                            <MessageCircleMoreIcon className="size-4" />
                            <span className="text-xs">{localize('com_sop_task_description')}</span>
                        </Button>
                    </PopoverTrigger>
                    <PopoverContent hideWhenDetached className="w-96 border bg-white rounded-xl">
                        <p className='text-sm font-bold mb-2 flex gap-1.5 items-center'>
                            <div className='size-5 rounded-sm overflow-hidden'>
                                <div className='size-full rounded-full rounded-br-2xl bg-primary text-white text-center scale-75'>
                                    <span className='relative -top-1 '>...</span>
                                </div>
                            </div>
                            {localize('com_sop_task_description')}
                        </p>
                        <p className='text-sm overflow-y-scroll'
                            style={{ display: '-webkit-box', WebkitLineClamp: 8, WebkitBoxOrient: 'vertical' }}
                        >
                            {linsight?.question}
                        </p>
                        <div>
                            {
                                linsight?.files.map(file =>
                                    <div key={file.file_id} className="flex items-center space-x-3 flex-1 mt-4">
                                        <FileIcon className='size-5 min-w-4' type={getFileExtension(file.file_name)} />
                                        <span className="text-sm text-gray-900 flex-1">{file.file_name}</span>
                                    </div>
                                )
                            }
                        </div>
                    </PopoverContent>
                </Popover>

                {
                    versions.length > 0 && <Select value={versionId} onValueChange={setVersionId}>
                        <SelectTrigger className="h-7 rounded-lg px-3 border bg-white hover:bg-gray-50 data-[state=open]:border-blue-500">
                            <div className="flex items-center gap-2">
                                <span className="text-xs font-normal text-gray-600">{localize('com_sop_task_version')} {versions.find(task => task.id === versionId)?.name}</span>
                            </div>
                        </SelectTrigger>
                        <SelectContent className="bg-white rounded-lg p-2 w-52 shadow-md">
                            {
                                versions.map(task => <SelectItem key={task.id} value={task.id} className="text-xs px-3 py-2 hover:bg-gray-50">
                                    {task.name}
                                </SelectItem>)
                            }
                        </SelectContent>
                    </Select>
                }
            </div>
        </div>
    );
};


const useCurrentTitle = () => {
    const { conversationId } = useParams();

    const { data } =
        useConversationsInfiniteQuery(
            {
                pageNumber: '1',
                isArchived: false,
            },
        );

    const title = useMemo(() => {
        // 初始化列表or搜索数据获取
        const conversations = data?.pages.flatMap((page) => page.conversations) ||
            [];
        const conversation = conversations.find((vo) => vo.conversationId === conversationId);
        return conversation?.title
    }, [conversationId, data]);

    return title
}