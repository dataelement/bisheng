import { Button } from '@bisheng/ui';
import Convo from '~/components/Conversations/Convo';
import { ApiRequestFailure } from '~/components/ApiRequestFailure';
import { useLocalize } from '~/hooks';
import { useProjectConversations } from '~/hooks/useChatProjects';

interface ProjectConversationsProps { projectId: string; onNavigate: () => void; }

export function ProjectConversations({ projectId, onNavigate }: ProjectConversationsProps) {
  const query = useProjectConversations(projectId);
  const localize = useLocalize();
  const conversations = query.data?.pages.flatMap(page => page.data) ?? [];
  return <>
    {conversations.map(conversation => <Convo key={conversation.conversationId} compact className="pl-8" isLatestConvo={false} conversation={conversation} retainView={() => undefined} toggleNav={onNavigate} />)}
    {query.isLoading && <p role="status" className="pl-8 text-caption text-text-3">{localize('project_sync.loading')}</p>}
    {query.isError && <ApiRequestFailure error={query.error} onRetry={query.refetch} />}
    {query.isSuccess && conversations.length === 0 && <p className="pl-8 text-caption text-text-3">{localize('com_workbench_sidebar.project_empty')}</p>}
    {query.hasNextPage && <Button color="default" variant="text" size="small" loading={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>{localize('project_sync.more')}</Button>}
  </>;
}
