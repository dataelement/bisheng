import { Button } from '@bisheng/ui';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { getDshUsageSummary } from '~/api/dsh';
import { AccountSection } from '~/components/Settings/sections/AccountSection';
import { StorageSection } from '~/components/Settings/sections/StorageSection';
import { ApprovalPane } from '~/components/approval/ApprovalPane';
import { DshUsageCalendar } from '~/components/dsh/DshUsageCalendar';
import { NotificationPane } from '~/components/messageApproval/NotificationPane';
import type { ApprovalCenterTarget } from '~/components/messageApproval/NotificationRow';
import { useAuthContext, useLocalize } from '~/hooks';
import { usePersonalTokenEnabled } from '~/hooks/useVersionManagementEnabled';
import type { DesktopSettingsSection } from '../desktopSettings';
import { AiAccessPane } from './AiAccessPane';

function DesktopAccountPane() {
  const { user } = useAuthContext();
  const [avatarUrl, setAvatarUrl] = useState(user?.avatar ?? '');
  // Desktop owns enterprise logout. Reuse only the existing account editor here.
  return <AccountSection username={user?.username ?? ''} avatarUrl={avatarUrl} onAvatarUpdated={setAvatarUrl} />;
}

function DesktopUsagePane() {
  const { user } = useAuthContext();
  const t = useLocalize();
  const usage = useQuery({
    queryKey: ['dsh-self-usage-summary', user?.id],
    enabled: Boolean(user?.id),
    retry: false,
    staleTime: 0,
    queryFn: ({ signal }) => getDshUsageSummary(signal),
  });
  return <div className="flex flex-col gap-6">
    <StorageSection />
    {usage.isLoading ? <p role="status">{t('dsh_loading')}</p> : usage.isError ?
      <div role="alert">{t('dsh_load_error')} <Button variant="link" onClick={() => void usage.refetch()}>{t('dsh_retry')}</Button></div> :
      usage.data ? <DshUsageCalendar summary={usage.data} /> : null}
  </div>;
}

interface DesktopSettingsPaneProps {
  section: DesktopSettingsSection;
  onCountsChanged?: () => void;
}

function DesktopMessagesPane({ section, onCountsChanged }: DesktopSettingsPaneProps) {
  const t = useLocalize();
  const [compactView, setCompactView] = useState<'list' | 'detail'>('list');
  const [target, setTarget] = useState<ApprovalCenterTarget | null>(null);
  if (section === 'notifications' && !target) {
    return <NotificationPane open onOpenApprovalCenter={next => { setTarget(next); setCompactView('detail'); }} onUnreadMaybeChanged={onCountsChanged} />;
  }
  return <div className="flex min-h-0 flex-1 flex-col">
    {target && <Button variant="link" className="mb-2 self-start" onClick={() => setTarget(null)}>{t('com_ui_go_back')}</Button>}
    <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[260px_minmax(0,1fr)]">
      <ApprovalPane open activeTab={target?.tab ?? (section === 'my-requests' ? 'my_requests' : 'my_tasks')} target={target ?? undefined}
        compactView={compactView} setCompactView={setCompactView} onPendingCountMaybeChanged={onCountsChanged} />
    </div>
  </div>;
}

/** Content-only composition: the native settings shell owns navigation, language and logout. */
export function DesktopSettingsPane({ section, onCountsChanged }: DesktopSettingsPaneProps) {
  const t = useLocalize();
  const personalTokenEnabled = usePersonalTokenEnabled();
  useEffect(() => {
    window.dshChatPresentation?.reportSettings?.(section);
    const close = (event: KeyboardEvent) => {
      // Nested dialogs retain Escape first; the document-level fallback closes the host shell.
      if (event.defaultPrevented || document.querySelector('[role="dialog"][data-state="open"]')) return;
      if (event.key === 'Escape' || ((event.metaKey || event.ctrlKey) && event.key === ',')) {
        event.preventDefault();
        window.dshChatPresentation?.requestSettingsClose?.();
      }
      if (event.key === 'Tab') {
        const controls = [...document.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]')].filter(node => node.getClientRects().length > 0);
        const edge = event.shiftKey ? controls[0] : controls[controls.length - 1];
        if (!controls.length || document.activeElement === edge) {
          event.preventDefault();
          window.dshChatPresentation?.requestSettingsFocus?.(event.shiftKey ? 'previous' : 'next');
        }
      }
    };
    document.addEventListener('keydown', close);
    return () => document.removeEventListener('keydown', close);
  }, [section]);
  const messages = section === 'my-tasks' || section === 'my-requests' || section === 'notifications';
  return <main className="flex h-[100dvh] min-h-0 flex-col overflow-auto bg-background p-1 text-text-1" data-desktop-settings-content={section}>
    {section === 'account' && <DesktopAccountPane />}
    {section === 'desktop-usage' && <DesktopUsagePane />}
    {section === 'ai-access' && (personalTokenEnabled ? <AiAccessPane /> : <p role="status">{t('com_ai_access.disabled_notice')}</p>)}
    {messages && <DesktopMessagesPane section={section} onCountsChanged={onCountsChanged} />}
  </main>;
}
