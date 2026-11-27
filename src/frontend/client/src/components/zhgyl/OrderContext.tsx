import { Link } from 'react-router-dom';
import { useLocalize } from '~/hooks';
import type { WorkspaceOrder } from './orderDataset';

export function OrderContext({ order, compact = false }: { order: WorkspaceOrder; compact?: boolean }) {
  const t = useLocalize();
  const amount = `${order.amount.toLocaleString('zh-CN', { maximumFractionDigits: 4 })} ${order.currency}`;
  if (compact) return <div className="zh-ai-thread-context" aria-label={t('zhgyl.currentOrder')}><strong>{t('zhgyl.currentThreadOrder', { order: order.number })}</strong><span>{order.supplier} · {amount}</span></div>;
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
  const dateText = (date: string) => {
    const days = Math.round((Date.parse(`${date}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86400000);
    return <b key={date}>{date}<small className={days < 0 ? 'past' : days === 0 ? 'today' : days <= 7 ? 'soon' : 'future'}>{t(days < 0 ? 'zhgyl.pastDays' : days === 0 ? 'zhgyl.todayDue' : 'zhgyl.futureDays', { count: Math.abs(days) })}</small></b>;
  };
  const groups = [
    ['paymentDate', order.invoices.map(row => row.due)],
    ['deliveryDate', order.lines.map(row => row.due)],
    ['settlementDate', order.settlements.map(row => row.date)],
  ] as const;
  return <section className="zh-ai-order-context" aria-label={t('zhgyl.currentOrder')}>
    <div className="zh-context-head"><div><span>{t('zhgyl.currentOrder')}</span><h2>{order.number}</h2></div><Link to={`/c/new?module=order-tracking&order=${encodeURIComponent(order.id)}`}>{t('zhgyl.orderDetails')}</Link></div>
    <div className="zh-context-meta"><div><span>{t('zhgyl.supplier')}</span><b>{order.supplier}</b></div><div><span>{t('zhgyl.material')}</span><b>{[...new Set(order.lines.map(line => `${line.material} · ${line.part}`))].join('；')}</b></div><div><span>{t('zhgyl.amount')}</span><b>{amount}</b></div></div>
    <div className="zh-context-dates">{groups.map(([label, values]) => {
      const dates = [...new Set(values.filter((date): date is string => !!date))].sort();
      return <div key={label}><span>{t(`zhgyl.${label}`)}</span>{dates.length ? dates.slice(0, 2).map(dateText) : <b>{t('zhgyl.missingDate')}</b>}{dates.length > 2 && <small>{t('zhgyl.dateCount', { count: dates.length })}</small>}</div>;
    })}</div><p>{t('zhgyl.orderContextHint')}</p>
  </section>;
}
