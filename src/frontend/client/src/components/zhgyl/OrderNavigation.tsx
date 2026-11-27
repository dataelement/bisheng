import { Link } from 'react-router-dom';
import { useLocalize } from '~/hooks';

export function OrderNavigation({ view }: { view: string }) {
  const t = useLocalize();
  const tabs = [['orders','orderOverview'],['workbench','orderWorkbench'],['reminders','orderReminders'],['ai','orderAi']];
  return <nav className="zh-native-orders-nav" aria-label={t('zhgyl.orderNav')}><div className="zh-order-tabs">
    {tabs.map(([key,label]) => <Link key={key} data-order-view={key} to={key === 'ai' ? '/c/new?agent=orders' : `/c/new?module=order-tracking&view=${key}`} className={view === key ? 'active' : ''} aria-current={view === key ? 'page' : undefined}>{t(`zhgyl.${label}`)}</Link>)}
  </div></nav>;
}
