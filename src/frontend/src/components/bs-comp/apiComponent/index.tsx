import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import ApiAccess from './ApiAccess';
import ApiAccessFlow from './ApiAccessFlow';
import ApiAccessSkill from './ApiAccessSkill';
import ChatLink from './ChatLink';

enum API_TYPE {
    ASSISTANT = 'assistant',
    SKILL = 'skill',
    FLOW = 'flow'
}

type MenuItem = {
    key: string;
    labelKey: string;
    component: React.ReactNode;
};

interface ApiMainPageProps {
    /** 
     * API 类型，决定显示哪种类型的接入方式
     * @default API_TYPE.ASSISTANT
     */
    type?: API_TYPE;
}

const ApiMainPage = ({ type = API_TYPE.ASSISTANT }: ApiMainPageProps) => {
    const { t } = useTranslation();
    const [activeMenu, setActiveMenu] = useState('api-access');

    // 菜单配置项
    const menuItems = useMemo((): MenuItem[] => [
        {
            key: 'api-access',
            labelKey: t('api.apiAccess'),
            component: getApiAccessComponent(type)
        },
        {
            key: 'no-login-link',
            labelKey: t('api.noLoginLink'),
            component: <ChatLink noLogin type={type} />
        },
        {
            key: 'login-link',
            labelKey: t('api.loginLink'),
            component: <ChatLink type={type} />
        }
    ], [type]);

    // 当前活动内容
    const activeContent = useMemo(
        () => menuItems.find(item => item.key === activeMenu)?.component,
        [activeMenu, menuItems]
    );

    return (
        <div className="flex size-full bg-background-main">
            {/* 左侧菜单组件 */}
            <MenuPanel
                items={menuItems}
                activeKey={activeMenu}
                onChange={setActiveMenu}
            />

            {/* 右侧内容区 */}
            <main className="flex-1 p-2 pl-0 overflow-y-auto" style={{ scrollBehavior: 'smooth' }}>
                {activeContent}
            </main>
        </div>
    );
};

// 辅助函数：获取 API 接入组件
const getApiAccessComponent = (type: API_TYPE) => {
    const components = {
        [API_TYPE.ASSISTANT]: <ApiAccess />,
        [API_TYPE.SKILL]: <ApiAccessSkill />,
        [API_TYPE.FLOW]: <ApiAccessFlow />
    };
    return components[type] || <ApiAccess />;
};

// 菜单面板组件
const MenuPanel = ({ items, activeKey, onChange }: {
    items: MenuItem[];
    activeKey: string;
    onChange: (key: string) => void
}) => (
    <aside className="w-52 text-white flex-shrink-0">
        <nav className="p-2">
            <ul className="space-y-4">
                {items.map((item) => (
                    <li key={item.key}>
                        <button
                            role="tab"
                            aria-selected={activeKey === item.key}
                            className={`w-full text-left p-2 pl-6 rounded transition-colors ${activeKey === item.key
                                ? 'bg-card hover:bg-card/90'
                                : 'hover:bg-card/50'
                                }`}
                            onClick={() => onChange(item.key)}
                        >
                            {item.labelKey}
                        </button>
                    </li>
                ))}
            </ul>
        </nav>
    </aside>
);

export default ApiMainPage;