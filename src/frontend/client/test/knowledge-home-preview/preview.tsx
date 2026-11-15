// Fixtures exist only in this separately launched test harness.
import { createContext, useContext, useMemo, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createRoot } from 'react-dom/client';
import type { KnowledgeSpace } from '../../src/api/knowledge';
import fixtureContent from './fixtures.zh-CN.json';
import translations from '../../src/locales/zh-Hans/translation.json';
import { KnowledgeHomePage } from '../../src/pages/knowledge/KnowledgeHomePage';
import '@bisheng/ui/tokens.css';
import '../../src/style.css';
import '../../src/mobile.css';
import './preview.css';

interface FixtureState { count: number; long: boolean; pinnedIds: Set<string>; onPin: (id: string, pinned: boolean) => void }
const FixtureContext = createContext<FixtureState>({ count: 7, long: false, pinnedIds: new Set(), onPin: () => undefined });
const noop = () => undefined;
export const SpaceSortType = { UPDATE_TIME: 'update_time' };
export const showApiError = (error: unknown) => console.error(error);
export const useConfirm = () => async () => false;
export const useWorkbenchMenuNames = () => ({ knowledge: translations.com_ui_knowledge_space });
export function useLocalize() {
  const { long } = useContext(FixtureContext);
  return (key: string, options?: Record<string, unknown>) => {
    if (long && key.startsWith('com_knowledge.home_next.sort_')) return fixtureContent.longSortHint;
    let value: unknown = translations;
    for (const part of key.split('.')) value = value && typeof value === 'object' ? (value as Record<string, unknown>)[part] : undefined;
    return typeof value === 'string' ? value.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options?.[name] ?? '')) : key;
  };
}
export function useKnowledgeSpaceLists() {
  const { count, long, pinnedIds } = useContext(FixtureContext);
  const spaces = useMemo(() => Array.from({ length: count }, (_, index): KnowledgeSpace => ({
    id: `fixture-${index}`, name: long ? `${fixtureContent.longTitle.repeat(10)} ${index + 1}` : `${fixtureContent.names[index % fixtureContent.names.length]}${index >= fixtureContent.names.length ? ` ${index + 1}` : ''}`,
    description: long ? fixtureContent.longDescription.repeat(30) : fixtureContent.description,
    creator: long ? fixtureContent.longOwner.repeat(10) : fixtureContent.owners[index % fixtureContent.owners.length], creatorId: 'fixture-owner',
    memberCount: 1, fileCount: 0, totalFileCount: 0,
    visibility: 'private' as KnowledgeSpace['visibility'], role: 'creator' as KnowledgeSpace['role'],
    isPinned: pinnedIds.has(`fixture-${index}`), createdAt: '2026-01-01', updatedAt: '2026-01-01', tags: [], isReleased: false,
  })), [count, long, pinnedIds]);
  const query = (offset: number) => ({ data: spaces.filter((_, index) => index % 3 === offset), isLoading: false, isFetching: false });
  return { mine: query(0), joined: query(1), department: query(2), error: null, retry: noop };
}
export const useKnowledgeSpaceActions = () => ({ actions: {}, ensureSpaceActions: noop, isSpaceActionsPending: () => false });
export function useSpaceActions() {
  const { onPin } = useContext(FixtureContext);
  return { handlePinSpace: async (id: string, pinned: boolean) => onPin(id, pinned), handleDeleteSpace: async () => undefined };
}

function Preview() {
  const [width, setWidth] = useState(1920);
  const [sidebar, setSidebar] = useState(389);
  const [count, setCount] = useState(7);
  const [long, setLong] = useState(false);
  const [pinnedIds, setPinnedIds] = useState<Set<string>>(() => new Set());
  const handleFixturePin = (id: string, pinned: boolean) => setPinnedIds((previous) => {
    const next = new Set(previous);
    if (pinned) next.add(id); else next.delete(id);
    return next;
  });
  const [height, setHeight] = useState(720);
  return <>
    <form className="preview-controls" onSubmit={(event) => event.preventDefault()}>
      <strong>Isolated component preview · fixture data · no backend writes</strong>
      <label>Outer width <input aria-label="Outer width" type="number" value={width} onChange={(event) => setWidth(Math.max(160, Number(event.target.value)))} /></label>
      <label>Navigation slot <select aria-label="Navigation slot" value={sidebar} onChange={(event) => setSidebar(Number(event.target.value))}>
        <option value={389}>389 · Figma reference</option><option value={240}>240 · existing Web sidebar</option><option value={64}>64 · hypothetical rail</option><option value={0}>0 · content upper bound</option>
      </select></label>
      <label>Cards <input aria-label="Cards" type="number" value={count} onChange={(event) => setCount(Math.min(200, Math.max(0, Number(event.target.value))))} /></label>
      <label>Panel height <input aria-label="Panel height" type="number" value={height} onChange={(event) => setHeight(Math.max(240, Number(event.target.value)))} /></label>
      <label><input aria-label="Long content" type="checkbox" checked={long} onChange={(event) => setLong(event.target.checked)} /> Long content</label>
      <label><input type="checkbox" checked={pinnedIds.has('fixture-0')} onChange={(event) => handleFixturePin('fixture-0', event.target.checked)} />First card pinned</label>
      <button type="button" onClick={() => { setWidth(window.innerWidth); setSidebar(0); }}>Fit browser</button>
    </form>
    <div className="preview-canvas">
      <div className="preview-shell" data-testid="preview-shell" style={{ width, height }}>
        {sidebar > 0 ? <aside className="preview-sidebar" style={{ width: sidebar }}>Navigation slot<br />Test geometry only<br />{sidebar}px</aside> : null}
        <main className="preview-main">
          <FixtureContext.Provider value={{ count, long, pinnedIds, onPin: handleFixturePin }}>
            <KnowledgeHomePage onSpaceSelect={noop} onCreateSpace={noop} onSpaceSettings={noop} onKnowledgeSquare={noop} />
          </FixtureContext.Provider>
        </main>
      </div>
    </div>
  </>;
}

createRoot(document.getElementById('root')!).render(<QueryClientProvider client={new QueryClient()}><Preview /></QueryClientProvider>);

// Fixture cards already carry creators; never call a real detail API from this harness.
export async function getSpaceInfoApi(): Promise<KnowledgeSpace> {
  throw new Error("Space detail is unavailable in the isolated fixture preview");
}
