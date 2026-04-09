import type { AppItem } from '~/@types/app';
import { Share2, Plus, ArrowLeftRight } from 'lucide-react';
import AppAvator from '~/components/Avator';
import { useLocalize } from '~/hooks';

interface AppInfoCardProps {
  app: AppItem;
  onShare: () => void;
  onNewChat: () => void;
  onSwitchApp: () => void;
  switchDisabled?: boolean;
}

/**
 * App info card displayed at the top of the chat sidebar.
 * Shows app avatar, name, description and action buttons.
 */
export function AppInfoCard({
  app,
  onShare,
  onNewChat,
  onSwitchApp,
  switchDisabled,
}: AppInfoCardProps) {
  const localize = useLocalize();
  return (
    <div className="px-4 mb-6">
      <div className="bg-white border border-gray-100 rounded-2xl p-4 shadow-sm">
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3 min-w-0">
            <AppAvator
              className="size-10 min-w-10"
              url={app.logo}
              id={app.id as any}
              flowType={String(app.flow_type)}
            />
            <div className="overflow-hidden">
              <h3 className="font-bold text-gray-900 truncate">{app.name}</h3>
              <p className="text-xs text-gray-400 truncate">
                {app.description || '暂无描述'}
              </p>
            </div>
          </div>
          <button
            onClick={onSwitchApp}
            disabled={switchDisabled}
            className="p-1 text-gray-300 hover:text-gray-500 transition-colors disabled:opacity-30 disabled:cursor-not-allowed mt-1"
            title={switchDisabled ? '暂无可切换应用' : '切换应用'}
          >
            <ArrowLeftRight size={14} />
          </button>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <button
            onClick={onShare}
            className="flex items-center justify-center gap-1 py-2 px-1 text-sm border border-gray-100 rounded-lg hover:bg-gray-50 text-gray-600 transition-colors"
          >
            <Share2 size={14} />
            {localize('com_app_share_app')}
          </button>
          <button
            onClick={onNewChat}
            className="flex items-center justify-center gap-1 py-2 px-1 text-sm border border-gray-100 rounded-lg hover:bg-gray-50 text-gray-600 transition-colors"
          >
            <Plus size={14} />
            {localize('com_knowledge_start_new_chat')}
          </button>
        </div>
      </div>
    </div>
  );
}
