import Cookies from 'js-cookie';
import { FileText, GanttChartIcon, Globe, LogOut } from 'lucide-react';
import { memo, useCallback, useState } from 'react';
import { useRecoilState } from 'recoil';
import { Dropdown, DropdownGroup, DropdownItem, DropdownSub, UserAvatar } from '@bisheng/ui';
import { GearIcon } from '~/components/svg';
import { useGetStartupConfig, useGetUserBalance } from '~/hooks/queries/data-provider';
import { useLocalize } from '~/hooks';
import { useAuthContext } from '~/hooks/AuthContext';
import store from '~/store';
import { getPlatformAdminPanelUrl } from '~/utils/platformAdminUrl';
import { canShowPlatformAdminEntry } from '~/utils/platformAccess';
import MyKnowledgeView from '../Chat/Input/Files/MyKnowledgeView';
import Settings from './Settings';

function AccountSettings() {
  const localize = useLocalize();
  const [langcode, setLangcode] = useRecoilState(store.lang);
  const changeLang = useCallback(
    (value: string) => {
      let userLang = value;
      if (value === 'auto') {
        userLang = navigator.language || navigator.languages[0];
      }

      requestAnimationFrame(() => {
        document.documentElement.lang = userLang;
      });
      setLangcode(userLang);
      Cookies.set('lang', userLang, { expires: 365 });
    },
    [setLangcode],
  );

  const { user, isAuthenticated, logout } = useAuthContext();
  const { data: startupConfig } = useGetStartupConfig();
  const balanceQuery = useGetUserBalance({
    enabled: !!isAuthenticated && startupConfig?.checkBalance,
  });
  const [showSettings, setShowSettings] = useState(false);
  const [showFiles, setShowFiles] = useRecoilState(store.showFiles);
  const [showKnowledge, setShowKnowledge] = useRecoilState(store.showKnowledge);

  const showAdminEntry = canShowPlatformAdminEntry({
    role: user?.role,
    plugins: user?.plugins,
    is_department_admin: user?.is_department_admin,
    has_admin_console: user?.has_admin_console,
  });

  return (
    <div className='mt-text-sm h-auto w-full items-center gap-2 rounded-xl p-2 text-sm'>
      <div
        className="flex gap-2 text-sm px-3 py-2 mb-2 items-center rounded-xl cursor-pointer hover:bg-[#EBEFF8]"
        onClick={() => setShowKnowledge(true)}
      >
        <FileText className="icon-md" />
        <div>{localize('com_nav_personal_knowledge')}</div>
      </div>
      <div className='h-[1px] bg-gray-200'></div>
      <Dropdown
        menu={
          <>
            {showAdminEntry && (
              <DropdownItem
                icon={<GanttChartIcon />}
                onSelect={() => window.open(getPlatformAdminPanelUrl(), '_blank', 'noreferrer')}
              >
                {localize('com_nav_admin_panel')}
              </DropdownItem>
            )}
            <DropdownSub icon={<Globe />} label={localize('com_nav_language')}>
              <DropdownGroup label={localize('com_nav_language_label')}>
                <DropdownItem checked={langcode === 'zh-Hans'} onSelect={() => changeLang('zh-Hans')}>
                  {localize('com_nav_lang_chinese')}
                </DropdownItem>
                <DropdownItem checked={langcode === 'en-US'} onSelect={() => changeLang('en-US')}>
                  {localize('com_nav_lang_english')}
                </DropdownItem>
                <DropdownItem checked={langcode === 'ja'} onSelect={() => changeLang('ja')}>
                  {localize('com_nav_lang_japanese')}
                </DropdownItem>
              </DropdownGroup>
            </DropdownSub>
            <DropdownItem icon={<LogOut />} onSelect={logout}>
              {localize('com_nav_log_out')}
            </DropdownItem>
          </>
        }
      >
        <div className='cursor-pointer mt-text-sm mt-2 flex h-auto w-full items-center gap-2 rounded-xl p-2 text-sm transition-all duration-200 ease-in-out hover:bg-[#EBEFF8]'>
          <div className="-ml-0.9 -mt-0.8 h-8 w-8 flex-shrink-0">
            <UserAvatar className="size-8" fallbackClassName="text-caption" name={user?.username} src={user?.avatar} />
          </div>
          <div
            className="mt-2 grow overflow-hidden text-ellipsis whitespace-nowrap text-left text-text-primary"
            style={{ marginTop: '0', marginLeft: '0' }}
          >
            {user?.name ?? user?.username ?? localize('com_nav_user')}
          </div>
        </div>
      </Dropdown>
      {/* {showFiles && <FilesView open={showFiles} onOpenChange={setShowFiles} />} */}
      {showKnowledge && <MyKnowledgeView open={showKnowledge} onOpenChange={setShowKnowledge} />}
      {showSettings && <Settings open={showSettings} onOpenChange={setShowSettings} />}
    </div>
  );
}

export default memo(AccountSettings);
