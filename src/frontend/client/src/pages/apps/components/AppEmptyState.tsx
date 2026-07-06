import { ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { EmptyStateIllustration } from '~/components/illustrations';
import { useLocalize } from '~/hooks';

/**
 * Empty state for app center home when user has no chat history.
 * Shows prompt text and a link to the explore page.
 */
export function AppEmptyState() {
  const localize = useLocalize();
  return (
    <div className="flex flex-col items-center">
      <EmptyStateIllustration className="size-[120px] mb-4 opacity-90" />
      <div className="text-[14px] font-normal text-[#999999] flex items-center gap-1">
        {localize('com_app.empty_go_explore')}
        <Link
          to="/apps/explore"
          className="text-blue-500 hover:text-blue-600 flex items-center font-medium transition-colors"
        >
          {localize('com_app.explore_more')}
          <ArrowRight size={14} className="ml-0.5" />
        </Link>
      </div>
    </div>
  );
}
