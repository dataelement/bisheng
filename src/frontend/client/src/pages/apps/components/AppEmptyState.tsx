import { ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';

/**
 * Empty state for app center home when user has no chat history.
 * Shows prompt text and a link to the explore page.
 */
export function AppEmptyState() {
  return (
    <div className="flex flex-col items-center justify-center flex-1">
      <img
        className="size-[120px] mb-3 object-contain opacity-90"
        src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
        alt="empty"
      />
      <div className="text-sm text-gray-500 flex items-center gap-1">
        暂无使用过的应用，可以前往应用广场
        <Link
          to="/apps/explore"
          className="text-blue-500 hover:text-blue-600 flex items-center font-medium transition-colors"
        >
          探索更多应用
          <ArrowRight size={14} className="ml-0.5" />
        </Link>
      </div>
    </div>
  );
}
