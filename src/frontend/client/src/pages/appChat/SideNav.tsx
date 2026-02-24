import { ChevronLeft, Share2, Plus, MessageSquare, ArrowLeftRight } from 'lucide-react';

export function SideNav() {
    // 模拟数据
    const conversations = [
        { id: '1', title: '新对话', active: true },
    ];

    return (
        <div className="w-[280px] h-full bg-[#f9fbff] border-r border-gray-100 flex flex-col overflow-hidden">
            {/* 顶部返回区域 */}
            <div className="flex items-center gap-3 p-4">
                <button className="p-2 bg-white border border-gray-200 rounded-xl shadow-sm hover:bg-gray-50 transition-colors">
                    <ChevronLeft size={18} className="text-gray-600" />
                </button>
                <span className="text-lg font-medium text-gray-800">应用对话</span>
            </div>

            {/* 智能体卡片区域 */}
            <div className="px-4 mb-6">
                <div className="bg-white border border-gray-100 rounded-2xl p-4 shadow-sm">
                    <div className="flex items-start justify-between mb-4">
                        <div className="flex items-center gap-3">
                            <div className="w-10 h-10 bg-blue-600 rounded-lg flex items-center justify-center text-white">
                                {/* 模拟图标 */}
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /></svg>
                            </div>
                            <div className="overflow-hidden">
                                <h3 className="font-bold text-gray-900 truncate flex items-center gap-1">
                                    🚀文旅IP生成
                                </h3>
                                <p className="text-xs text-gray-400 truncate">自动生成文旅 IP 角色设定...</p>
                            </div>
                        </div>
                        <ArrowLeftRight size={14} className="text-gray-300 mt-1" />
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                        <button className="flex items-center justify-center gap-1 py-2 px-1 text-sm border border-gray-100 rounded-lg hover:bg-gray-50 text-gray-600 transition-colors">
                            <Share2 size={14} />
                            分享应用
                        </button>
                        <button className="flex items-center justify-center gap-1 py-2 px-1 text-sm border border-gray-100 rounded-lg hover:bg-gray-50 text-gray-600 transition-colors">
                            <Plus size={14} />
                            开启新对话
                        </button>
                    </div>
                </div>
            </div>

            {/* 会话列表区域 */}
            <div className="flex-1 px-3 overflow-y-auto">
                <div className="px-2 mb-2 text-xs font-medium text-gray-400">今天</div>
                {conversations.map((item) => (
                    <div
                        key={item.id}
                        className={`
              group flex items-center gap-3 px-3 py-3 rounded-xl cursor-pointer transition-all
              ${item.active ? 'bg-[#eef4ff] text-blue-600' : 'hover:bg-gray-100 text-gray-700'}
            `}
                    >
                        <MessageSquare size={18} className={item.active ? 'text-blue-500' : 'text-gray-400'} />
                        <span className="text-[14px] font-medium">{item.title}</span>
                    </div>
                ))}
            </div>
        </div>
    );
}