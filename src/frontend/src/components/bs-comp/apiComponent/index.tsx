import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import ApiAccess from './ApiAccess';
import ApiAccessFlow from './ApiAccessFlow';
import ApiAccessSkill from './ApiAccessSkill';
import ChatLink from './ChatLink';

const enum API_TYPE {
    ASSISTANT = 'assistant',
    SKILL = 'skill',
    FLOW = 'flow'
}

/**
 * 
 * @param type 助手/技能/工作流
 * @ 助手id/技能useContext(TabsContext)/ 
 */
const ApiMainPage = ({ type = API_TYPE.ASSISTANT }) => {
    const [activeMenu, setActiveMenu] = useState('api-access');
    const { t } = useTranslation()

    const renderContent = () => {
        switch (activeMenu) {
            case 'api-access':
                return type === API_TYPE.ASSISTANT ? <ApiAccess /> : type === API_TYPE.SKILL ? <ApiAccessSkill /> : <ApiAccessFlow />;
            case 'no-login-link':
                return <ChatLink noLogin type={type} />;
            case 'login-link':
            // return <ChatLink type={type} />;
            default:
                return <ApiAccess />;
        }
    };

    return (
        <div className="flex size-full bg-background-main">
            {/* 左侧竖向菜单 */}
            <aside className="w-52 text-white flex-shrink-0">
                <nav className="p-2">
                    <ul className="space-y-4">
                        <li>
                            <button
                                className={`w-full text-left ${activeMenu === 'api-access' ? 'bg-card' : ''} p-2 pl-6 rounded`}
                                onClick={() => setActiveMenu('api-access')}
                            >
                                {t('api.apiAccess')}
                            </button>
                        </li>
                        <li>
                            <button
                                className={`w-full text-left ${activeMenu === 'no-login-link' ? 'bg-card' : ''} p-2 pl-6 rounded`}
                                onClick={() => setActiveMenu('no-login-link')}
                            >
                                {t('api.noLoginLink')}
                            </button>
                        </li>
                        <li>
                            <button
                                className={`w-full text-left ${activeMenu === 'login-link' ? 'bg-card' : ''} p-2 pl-6 rounded`}
                                onClick={() => setActiveMenu('login-link')}
                            >
                                {t('api.loginLink')}
                            </button>
                        </li>
                    </ul>
                </nav>
            </aside>

            {/* 右侧内容区 */}
            <main className="flex-1 p-2 pl-0 overflow-y-auto">
                {renderContent()}
            </main>
        </div>
    );
};

export default ApiMainPage;
