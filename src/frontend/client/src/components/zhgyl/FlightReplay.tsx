import { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useLocalize } from '~/hooks';
import { advisorScene } from './scenes';

export function FlightReplay() {
  const { pathname, search } = useLocation();
  const scene = advisorScene(search);
  const home = pathname === '/c/new' && !new URLSearchParams(search).has('module') && (!scene || scene === 'select');
  const t = useLocalize();
  const [reduced, setReduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const frame = useRef(0);
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(media.matches);
    media.addEventListener('change', update);
    return () => { media.removeEventListener('change', update); cancelAnimationFrame(frame.current); };
  }, []);
  if (!home) return null;
  const handleReplay = () => {
    if (reduced) return;
    delete document.body.dataset.flightRun;
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      frame.current = requestAnimationFrame(() => { document.body.dataset.flightRun = 'on'; });
    });
  };
  return <div className="flight-preview-controls"><button type="button" className="replay-flight" disabled={reduced} title={reduced ? t('zhgyl.reducedMotion') : undefined} onClick={handleReplay}>{t('zhgyl.replay')}</button></div>;
}
