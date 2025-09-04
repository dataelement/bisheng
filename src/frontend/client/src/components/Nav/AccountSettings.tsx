import * as Select from '@ariakit/react/select';
import { FileText, GanttChartIcon, LogOut } from 'lucide-react';
import { memo, useState } from 'react';
import { useRecoilState } from 'recoil';
import MyKnowledgeView from '~/components/Chat/Input/Files/MyKnowledgeView';
import { UserIcon } from '~/components/svg';
import { useGetStartupConfig, useGetUserBalance } from '~/data-provider';
import { useLocalize } from '~/hooks';
import { useAuthContext } from '~/hooks/AuthContext';
import useAvatar from '~/hooks/Messages/useAvatar';
import store from '~/store';
import Settings from './Settings';

function AccountSettings() {
  const localize = useLocalize();
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
    <Select.SelectProvider>
      {/* <Select.Select
        aria-label={localize('com_nav_account_settings')}
        className="mt-text-sm flex h-auto w-full items-center gap-2 rounded-xl p-2 text-sm transition-all duration-200 ease-in-out hover:bg-accent"
      >
        <div>12</div>
      </Select.Select> */}
      <div className='h-4'></div>
      <div
        className="flex gap-2 text-sm px-3 py-2 mb-2 items-center rounded-xl cursor-pointer hover:bg-[#EBEFF8]"
        onClick={() => setShowKnowledge(true)}
      >
        <FileText className="icon-md" />
        <div>个人知识库</div>
      </div>
      <div className='h-[1px] bg-gray-200'></div>
      <Select.Select
        aria-label={localize('com_nav_account_settings')}
        data-testid="nav-user"
        className="mt-text-sm mt-2 flex h-auto w-full items-center gap-2 rounded-xl p-2 text-sm transition-all duration-200 ease-in-out hover:bg-[#EBEFF8]"
      >
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
      </Select.Select>
      <Select.SelectPopover
        className="popover-ui w-[235px]"
        style={{
          transformOrigin: 'bottom',
          marginRight: '0px',
          translate: '0px',
        }}
      >
        {/* <div className="text-token-text-secondary ml-3 mr-2 py-2 text-sm" role="note">
          {user?.email ?? localize('com_nav_user')}
        </div> */}
        {/* <DropdownMenuSeparator /> */}
        {/* {startupConfig?.checkBalance === true &&
          balanceQuery.data != null &&
          !isNaN(parseFloat(balanceQuery.data)) && (
            <>
              <div className="text-token-text-secondary ml-3 mr-2 py-2 text-sm" role="note">
                {localize('com_nav_balance')}: {parseFloat(balanceQuery.data).toFixed(2)}
              </div>
              <DropdownMenuSeparator />
            </>
          )} */}
        {/* <Select.SelectItem
          value=""
          onClick={() => setShowFiles(true)}
          className="select-item text-sm"
        >
          <FileText className="icon-md" aria-hidden="true" />
          {localize('com_nav_my_files')}
        </Select.SelectItem> */}
        {/* {startupConfig?.helpAndFaqURL !== '/' && (
          <Select.SelectItem
            value=""
            onClick={() => window.open(startupConfig?.helpAndFaqURL, '_blank')}
            className="select-item text-sm"
          >
            <LinkIcon aria-hidden="true" />
            {localize('com_nav_help_faq')}
          </Select.SelectItem>
        )} */}
        {/* <Select.SelectItem
          value=""
          onClick={() => setShowSettings(true)}
          className="select-item text-sm"
        >
          <GearIcon className="icon-md" aria-hidden="true" />
          {localize('com_nav_settings')}
        </Select.SelectItem> */}
        {/* <DropdownMenuSeparator /> */}
        <a href={"/" + __APP_ENV__.BISHENG_HOST} target='_blank'>
          <Select.SelectItem
            aria-selected={true}
            className="select-item text-sm"
          >
            <GanttChartIcon className="icon-md" />
            管理后台
          </Select.SelectItem>
        </a>
        <Select.SelectItem
          aria-selected={true}
          onClick={() => logout()}
          value="logout"
          className="select-item text-sm"
        >
          <LogOut className="icon-md" />
          {localize('com_nav_log_out')}
        </Select.SelectItem>
      </Select.SelectPopover>
      {/* {showFiles && <FilesView open={showFiles} onOpenChange={setShowFiles} />} */}
      {showKnowledge && <MyKnowledgeView open={showKnowledge} onOpenChange={setShowKnowledge} />}
      {showSettings && <Settings open={showSettings} onOpenChange={setShowSettings} />}
    </Select.SelectProvider>
  );
}

export default memo(AccountSettings);
