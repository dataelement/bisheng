import Cookies from 'js-cookie';
import { Check, FileText, GanttChartIcon, Globe, LogOut } from 'lucide-react';
import { memo, useCallback, useState } from 'react';
import { useRecoilState } from 'recoil';
import { GearIcon, UserIcon } from '~/components/svg';
import { useGetStartupConfig, useGetUserBalance } from '~/data-provider';
import { useLocalize } from '~/hooks';
import { useAuthContext } from '~/hooks/AuthContext';
import useAvatar from '~/hooks/Messages/useAvatar';
import store from '~/store';
import MyKnowledgeView from '../Chat/Input/Files/MyKnowledgeView';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, DropdownMenuTrigger } from '../ui';
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

  const avatarSrc = useAvatar(user);
  const name = user?.avatar ?? user?.username ?? '';

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
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <div className='cursor-pointer mt-text-sm mt-2 flex h-auto w-full items-center gap-2 rounded-xl p-2 text-sm transition-all duration-200 ease-in-out hover:bg-[#EBEFF8]'>
            <div className="-ml-0.9 -mt-0.8 h-8 w-8 flex-shrink-0">
              <div className="relative flex">
                {name.length === 0 ? (
                  <div
                    style={{
                      backgroundColor: 'rgb(121, 137, 255)',
                      width: '32px',
                      height: '32px',
                      boxShadow: 'rgba(240, 246, 252, 0.1) 0px 0px 0px 1px',
                    }}
                    className="relative flex items-center justify-center rounded-full p-1 text-text-primary"
                    aria-hidden="true"
                  >
                    <UserIcon />
                  </div>
                ) : (
                  <div className="w-8 h-8 min-w-6 text-white bg-primary rounded-full flex justify-center items-center text-xs">{(user?.name ?? user?.username ?? localize('com_nav_user')).substring(0, 2).toUpperCase()}</div>
                  // <img
                  //   className="rounded-full"
                  //   src={(user?.avatar ?? '') || avatarSrc}
                  //   alt={`${name}'s avatar`}
                  // />
                )}
              </div>
            </div>
            <div
              className="mt-2 grow overflow-hidden text-ellipsis whitespace-nowrap text-left text-text-primary"
              style={{ marginTop: '0', marginLeft: '0' }}
            >
              {user?.name ?? user?.username ?? localize('com_nav_user')}
            </div>
          </div>
        </DropdownMenuTrigger>
        <DropdownMenuContent className='w-60 rounded-2xl'>
          {user?.plugins?.includes('backend') && <a href={"/" + __APP_ENV__.BISHENG_HOST} target='_blank'>
            <DropdownMenuItem className='select-item text-sm font-normal'>
              <GanttChartIcon className="icon-md" />
              {localize('com_nav_admin_panel')}
            </DropdownMenuItem>
          </a>}
          <DropdownMenuSub>
            <DropdownMenuSubTrigger className='select-item text-sm font-normal'>
              <Globe className="icon-md" />
              {localize('com_nav_language')}
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent className='w-40 rounded-2xl'>
              <span className='text-xs text-gray-400 pl-2'>{localize('com_nav_language_label')}</span>
              <DropdownMenuItem className='font-normal justify-between' onClick={() => changeLang('zh-Hans')}>
                {localize('com_nav_lang_chinese')}
                {langcode === 'zh-Hans' && <Check size={16} />}
              </DropdownMenuItem>
              <DropdownMenuItem className='font-normal justify-between' onClick={() => changeLang('en-US')}>
                {localize('com_nav_lang_english')}
                {langcode === 'en-US' && <Check size={16} />}
              </DropdownMenuItem>
              <DropdownMenuItem className='font-normal justify-between' onClick={() => changeLang('ja')}>
                {localize('com_nav_lang_japanese')}
                {langcode === 'ja' && <Check size={16} />}
              </DropdownMenuItem>
            </DropdownMenuSubContent>
          </DropdownMenuSub>
          {/* <DropdownMenuItem className='select-item text-sm font-normal'>
            <div className='w-full flex gap-2 items-center' onClick={() => setShowSettings(true)} >
              <GearIcon className="icon-md" aria-hidden="true" />
              {localize('com_nav_settings')}
            </div>
          </DropdownMenuItem> */}
          <DropdownMenuItem className='select-item text-sm font-normal'>
            <div className='w-full flex gap-2 items-center' onClick={logout} >
              <LogOut className="icon-md" />
              {localize('com_nav_log_out')}
            </div>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {/* {showFiles && <FilesView open={showFiles} onOpenChange={setShowFiles} />} */}
      {showKnowledge && <MyKnowledgeView open={showKnowledge} onOpenChange={setShowKnowledge} />}
      {showSettings && <Settings open={showSettings} onOpenChange={setShowSettings} />}
    </div>
  );
}

export default memo(AccountSettings);
