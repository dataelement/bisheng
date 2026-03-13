import { ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';

/**
 * Empty state for app center home when user has no chat history.
 * Shows prompt text and a link to the explore page.
 */
export function AppEmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 flex-1">
      <div className="mb-6 opacity-80">
        <svg
          width="120"
          height="120"
          viewBox="0 0 120 120"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path
            d="M60 15L98.9711 37.5V82.5L60 105L21.0289 82.5V37.5L60 15Z"
            stroke="#3B82F6"
            strokeWidth="2"
            strokeDasharray="4 4"
          />
          <circle cx="60" cy="60" r="22" stroke="#3B82F6" strokeWidth="2" />
          <circle cx="60" cy="60" r="6" stroke="#3B82F6" strokeWidth="2" strokeDasharray="2 2" />
        </svg>
      </div>
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
