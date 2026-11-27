import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { advisorScene } from './scenes';

/** Set the approved D palette only while its source views are active. */
export function useWorkspaceTheme() {
  const { pathname, search } = useLocation();
  const scene = advisorScene(search);
  const module = new URLSearchParams(search).get('module');
  const chat = /^\/c\/[^/]+\/?$/.test(pathname);
  const home = pathname === '/c/new' && !module && (!scene || scene === 'select');
  useEffect(() => {
    const body = document.body;
    body.classList.toggle('zh-workbench', chat && module !== 'procurement-forecast');
    body.classList.add('zh-sidebar-clean');
    body.classList.toggle('zh-orders-open', chat && module === 'order-tracking');
    body.classList.toggle('zh-orders-ai', chat && scene === 'orders');
    body.classList.toggle('zh-forecast-open', chat && module === 'procurement-forecast');
    if (home) { body.dataset.flightTheme = 'light'; body.dataset.flightRun = 'on'; }
    else { delete body.dataset.flightTheme; delete body.dataset.flightRun; }
    return () => {
      body.classList.remove('zh-workbench', 'zh-sidebar-clean', 'zh-orders-open', 'zh-orders-ai', 'zh-forecast-open');
      delete body.dataset.flightTheme; delete body.dataset.flightRun;
    };
  }, [chat, module, scene, home]);
}
