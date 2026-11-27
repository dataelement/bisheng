import type { AdvisorScene } from './scenes';

export function AdvisorIcon({ scene }: { scene: AdvisorScene }) {
  const paths = scene === 'orders' ? ['M5 3h14v18H5z','M9 8h6','M9 12h6','M9 16h4'] : scene === 'customs' ? ['M4 3h16v18H4z','M8 7h8','M8 11h8','M8 15h4'] : scene === 'procurement' ? ['M8 3h8l4 4v14H4V3h4Z','M8 3v5h8V3','M8 12h8','M8 16h5'] : ['M3 6h11v12H3z','M14 10h4l3 4v4h-7','M6 18a2 2 0 1 0 4 0','M15 18a2 2 0 1 0 4 0','M3 10h7'];
  return <svg viewBox="0 0 24 24" width="27" height="27" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths.map((d, index) => <path key={index} d={d} />)}</svg>;
}

export function AdvisorTaskIcon({ type }: { type: string }) {
  const paths: Record<string, string[]> = {
    search: ['M21 21l-4.4-4.4','M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0'],
    users: ['M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2','M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8','M22 21v-2a4 4 0 0 0-3-3.9','M16 3.1a4 4 0 0 1 0 7.8'],
    'receipt-text': ['M4 3l2 1 2-1 2 1 2-1 2 1 2-1 2 1 2-1v18l-2-1-2 1-2-1-2 1-2-1-2 1-2-1-2 1V3','M8 8h8','M8 12h8','M8 16h5'],
    truck: ['M2 5h13v13H2z','M15 9h4l3 4v5h-7','M8 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0','M20 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0'],
    files: ['M8 3h8l4 4v14H8z','M16 3v5h4','M4 3v14','M11 12h6','M11 16h6'],
    package: ['M3 7l9-5 9 5-9 5z','M3 7v10l9 5 9-5V7','M12 12v10','M7.5 4.5l9 5'],
  };
  return <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" data-task-icon={type}>{(paths[type] || paths.search).map((d, index) => <path key={index} d={d} />)}</svg>;
}

export function AdvisorNavIcon({ module }: { module: 'forecast' | 'orders' }) {
  return <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">{module === 'forecast' ? <path d="M4 4v16h16M7 14l4-5 4 3 5-7M16 5h4v4" /> : <><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M9 8h6M9 12h6M9 16h4" /></>}</svg>;
}
