import Cookies from 'js-cookie';
import { BookOpen, Globe, Home, Monitor, Wifi } from 'lucide-react';
import React, { useCallback, useMemo } from 'react';
import KeepAlive from 'react-activation';
import { matchPath, NavLink, useLocation, useOutlet } from 'react-router-dom';
import { useRecoilState } from 'recoil';
import { useGetBsConfig } from '~/data-provider';
import { useAuthContext, useLocalize } from '~/hooks';
import store from '~/store';
import { cn } from '~/utils';
import { UserPopMenu } from './UserPopMenu';

interface SidebarItemProps {
  icon: React.ReactNode;
  to: string;
  active: boolean; // 改为手动传入 active 状态
}

function SidebarItem({ icon, to, active }: SidebarItemProps) {
  return (
    <NavLink
      to={to}
      className={cn(
        "flex items-center justify-center p-3 rounded-lg cursor-pointer transition-colors hover:bg-[#e6edfc]",
        active && "bg-[#e6edfc]"
      )}
    >
      {React.cloneElement(icon as React.ReactElement, {
        className: cn("size-5", active ? "text-[#335CFF]" : "text-[#818181]"),
      })}
    </NavLink>
  );
}

function Sidebar() {
  const { pathname } = useLocation();
  const { data: bsConfig } = useGetBsConfig();
  const { user, logout } = useAuthContext();
  const localize = useLocalize();
  const [langcode, setLangcode] = useRecoilState(store.lang);

  // --- 高亮逻辑定义 ---
  const links = useMemo(() => [
    {
      to: '/c/new',
      icon: <Home />,
      isActive: /^\/(c|linsight)(\/|$)/.test(pathname)
    },
    {
      to: '/apps',
      icon: <Globe />,
      isActive: matchPath('/app/:id/:fid/:type', pathname) !== null || pathname.startsWith('/apps')
    },
    {
      to: '/channel',
      icon: <Wifi />,
      isActive: pathname.startsWith('/channel')
    },
    {
      to: '/knowledge',
      icon: <BookOpen />,
      isActive: pathname.startsWith('/knowledge')
    },
  ], [pathname]);

  const changeLang = useCallback((value: string) => {
    let userLang = value;
    if (value === 'auto') userLang = navigator.language || navigator.languages[0];
    setLangcode(userLang);
    Cookies.set('lang', userLang, { expires: 365 });
  }, [setLangcode]);

  const displayName = user?.name ?? user?.username ?? localize('com_nav_user');

  return (
    <div className="w-16 h-screen flex flex-col items-center justify-between py-4 px-2 shrink-0">
      <div className="flex flex-col gap-10 items-center">
        <div className="size-10 relative">
          <img src={__APP_ENV__.BASE_URL + bsConfig?.sidebarIcon.image} className="size-full" alt="logo" />
        </div>

        <div className="flex flex-col gap-4 items-center">
          {links.map(link => (
            <SidebarItem
              key={link.to}
              to={link.to}
              icon={link.icon}
              active={link.isActive}
            />
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-4 items-center">
        {user?.plugins?.includes('backend') && (
          <a href={__APP_ENV__.BISHENG_HOST} target='_blank' rel="noreferrer">
            <div title={localize('com_nav_admin_panel')} className="p-3 rounded-lg hover:bg-[#e6edfc] transition-colors">
              <Monitor className="size-5 text-[#818181]" />
            </div>
          </a>
        )}
        <div className="w-full h-px bg-[#ececec]" />

        {/* 用户下拉菜单 */}
        <UserPopMenu />
      </div>
    </div>
  );
}

export default function MainLayout() {
  const { pathname } = useLocation();
  const outlet = useOutlet();

  const cacheKey = useMemo(() => {
    if (/^\/(c|linsight|apps)(\/|$)/.test(pathname)) return 'home_tab';
    if (/^\/(channel|app|chat\/[^/]+\/[^/]+\/[^/]+)(\/|$)/.test(pathname)) return 'app_tab';
    if (pathname.startsWith('/subscription')) return 'subscription_tab';
    if (pathname.startsWith('/knowledge')) return 'knowledge_tab';
    return 'other';
  }, [pathname]);

  return (
    <div className="flex bg-[#F9F9F9]">
      <Sidebar />
      <main className="flex-1 h-screen relative p-2 pl-0">
        <KeepAlive
          name={cacheKey}
          id={cacheKey}
          saveScroll={true}
        >
          <div className='bg-white rounded-xl shadow-xl overflow-hidden h-[calc(100vh-16px)]'>
            {outlet}
          </div>
        </KeepAlive>
      </main>
    </div>
  );
}