import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useLocalize } from '~/hooks';
import { orderNavigation, workspaceAsset } from './scenes';
import { useOrderDataset } from './orderDataset';
import { OrderNavigation } from './OrderNavigation';

interface WorkspaceModuleProps { module: 'order-tracking' | 'procurement-forecast'; active?: boolean }
const paletteKeys = ['--aviation-page','--aviation-sidebar','--aviation-surface','--aviation-border','--aviation-hero-border','--aviation-input-border','--aviation-input-focus','--aviation-title','--aviation-hero-light'];

export function WorkspaceModule({ module, active = true }: WorkspaceModuleProps) {
  const t = useLocalize();
  const frame = useRef<HTMLIFrameElement>(null);
  const navigate = useNavigate();
  const { search } = useLocation();
  const orders = module === 'order-tracking';
  const dataset = useOrderDataset(orders && active);
  const [view, setView] = useState(new URLSearchParams(search).get('view') || 'orders');
  const [frameReady, setFrameReady] = useState(false);
  const [frameError, setFrameError] = useState(false);
  const sendRoute = useCallback(() => {
    const params = new URLSearchParams(search);
    frame.current?.contentWindow?.postMessage({ type: 'zh-order-route', view: params.get('view'), order: params.get('order'), mode: params.get('mode'), node: params.get('node') }, window.location.origin);
  }, [search]);
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (!orders || !active || event.origin !== window.location.origin || event.source !== frame.current?.contentWindow) return;
      if (event.data?.type === 'zh-order-ready') { setFrameReady(true); sendRoute(); }
      if (event.data?.type === 'zh-order-view' && ['orders','workbench','reminders'].includes(event.data.view)) setView(event.data.view);
      if (event.data?.type === 'zh-order-navigate') {
        const destination = orderNavigation(event.data.path, window.location.origin);
        if (destination) navigate(destination);
      }
    };
    window.addEventListener('message', receive);
    return () => window.removeEventListener('message', receive);
  }, [orders, active, navigate, sendRoute]);
  useEffect(() => { if (orders && active) sendRoute(); }, [orders, active, sendRoute]);
  const handleLoad = () => {
    if (orders && dataset.data) {
      try {
        if (!frame.current?.contentDocument?.querySelector('#dataset')) { setFrameError(true); return; }
        frame.current.contentWindow?.postMessage({ type: 'zh-order-dataset', dataset: dataset.data }, window.location.origin);
      } catch { setFrameError(true); }
    }
    if (!orders) {
      try {
        const document = frame.current?.contentDocument;
        if (!document?.querySelector('#query-form')) { setFrameError(true); return; }
        const target = document.documentElement;
        const source = getComputedStyle(window.document.documentElement);
        for (const key of paletteKeys) { const value = source.getPropertyValue(key).trim(); if (value) target.style.setProperty(key, value); }
        setFrameReady(true);
      } catch { setFrameError(true); }
    }
  };
  return <section hidden={!active} className="zhgyl-module" id={orders ? undefined : 'procurement-forecast-module'}>
    {orders && <OrderNavigation view={view} />}
    {!orders && frameError ? <div role="alert" className="zh-forecast-load-error">{t('zhgyl.forecastLoadFailed')} <button type="button" onClick={() => { setFrameError(false); setFrameReady(false); }}>{t('zhgyl.reopen')}</button></div> : orders && (dataset.isError || frameError) ? <div role="alert" className="zh-forecast-load-error">{t('zhgyl.orderLoadFailed')} <button type="button" onClick={() => { setFrameError(false); setFrameReady(false); if (dataset.isError) void dataset.refetch(); }}>{t('zhgyl.retry')}</button></div> : orders && !dataset.data ? <div role="status" className="zh-forecast-load-error">{t('zhgyl.orderLoading')}</div> : <iframe ref={frame} title={t(orders ? 'zhgyl.orders' : 'zhgyl.forecast')} src={orders ? workspaceAsset('order-tracking.html') : `${import.meta.env.BASE_URL.replace(/\/$/, '')}/procurement-forecast/?embed=1`} className={orders ? 'zh-orders-frame' : 'w-full flex-1 border-0'} style={{ visibility: frameReady ? 'visible' : 'hidden' }} onLoad={handleLoad} onError={() => setFrameError(true)} referrerPolicy="same-origin" sandbox={orders ? undefined : 'allow-scripts allow-same-origin allow-forms allow-downloads allow-popups allow-popups-to-escape-sandbox'} />}
  </section>;
}
