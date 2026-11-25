import { Pagination } from '@bisheng/ui';
import { useLocalize } from '~/hooks';

export const TAG_PAGE_SIZE = 50;
interface TagPaginationProps { page: number; total: number; onChange: (page: number) => void }
export function TagPagination({ page, total, onChange }: TagPaginationProps) {
  const localize = useLocalize();
  return <Pagination size="small" showQuickJumper={false} current={page} total={total} pageSize={TAG_PAGE_SIZE} onChange={onChange}
    locale={{ prev: localize('com_knowledge.move_previous_page'), next: localize('com_knowledge.move_next_page'), nav: localize('com_knowledge.provider_tags.pages') }} />;
}
