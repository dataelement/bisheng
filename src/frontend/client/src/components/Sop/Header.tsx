import { FileText, PanelRight } from 'lucide-react';
import { useMemo } from 'react';
import { useParams } from 'react-router-dom';
import { useConversationsInfiniteQuery } from '~/hooks/queries/data-provider';
import { useLocalize } from '~/hooks';
import { useLinsightManager } from '~/hooks/useLinsightManager';
import ShareChat from '../Share/ShareChat';
import { Skeleton } from '../ui';

export const Header = ({ isLoading, chatId, isSharePage, setVersionId, versionId, versions, onOpenWorkspace }) => {
    const { getLinsight } = useLinsightManager()
    const localize = useLocalize()
    const linsight = useMemo(() => {
        return getLinsight(versionId)
    }, [getLinsight, versionId])

    const title = useCurrentTitle()

    return (
        <div className="flex items-center justify-between p-4">
            {isLoading ?
                <Skeleton className="h-7 w-[250px] rounded-lg bg-gray-100 opacity-100" />
                : <div className="flex items-center gap-3">
                    {/* <FileText className="size-4" /> */}
                    <span className="text-base font-medium text-gray-900">
                        {title || linsight?.title}
                    </span>
                </div>
            }

            <div className="flex items-center gap-2">
                {!isSharePage && linsight?.session_id && (
                    <ShareChat type="linsight_session" chatId={linsight.session_id} versionId={versionId} labeled={false} />
                )}
                {!!linsight?.file_list?.length && (
                    <button
                        type="button"
                        onClick={onOpenWorkspace}
                        title={localize('com_linsight_workspace')}
                        aria-label="workspace"
                        className="flex h-7 w-7 items-center justify-center rounded-lg text-gray-600 hover:bg-gray-100"
                    >
                        <PanelRight size={16} />
                    </button>
                )}
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