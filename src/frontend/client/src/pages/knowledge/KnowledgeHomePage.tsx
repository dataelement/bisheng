import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useReducedMotion } from 'framer-motion';
import { Button as ProductButton } from '@bisheng/ui';
import { USE_PRODUCT_COMPONENTS } from './home/vnext/componentMode';
import { Outlined } from 'bisheng-icons';
import { SpaceSortType, type KnowledgeSpace } from '~/api/knowledge';
import { showApiError } from '~/api/request';
import { useLocalize, useWorkbenchMenuNames } from '~/hooks';
import { useKnowledgeSpaceLists } from './hooks/useKnowledgeSpaceLists';
import { useKnowledgeSpaceActions } from './hooks/useKnowledgeSpacePermissions';
import { useSpaceActions } from './hooks/useSpaceActions';
import { KnowledgeHomeSort } from './home/vnext/KnowledgeHomeSort';
import { KnowledgeHomeCard } from './home/vnext/KnowledgeHomeCard';
import { groupHomeSpaces, mergePinnedOrder, sortHomeSpaces, type HomeCategory, type HomeSort, type HomeSpace } from './home/vnext/homeSpaces';
import departmentIcon from './home/vnext/assets/menu-1.svg';
import createdIcon from './home/vnext/assets/menu-2.svg';
import joinedIcon from './home/vnext/assets/menu-3.png';
import tokens from './home/vnext/tokens.module.css';
import styles from './home/vnext/KnowledgeHomeNext.module.css';

interface KnowledgeHomePageProps {
  enabled?: boolean;
  category?: HomeCategory;
  onCategoryChange?: (category: HomeCategory) => void;
  onSpaceSelect: (space: KnowledgeSpace | null) => void;
  onCreateSpace: () => void;
  onSpaceSettings: (space: KnowledgeSpace) => void;
  onKnowledgeSquare: () => void;
}

const categories: HomeCategory[] = ['all', 'department', 'created', 'joined'];
const categoryIcons = { department: departmentIcon, created: createdIcon, joined: joinedIcon };

export function KnowledgeHomePage({ enabled = true, category: controlledCategory, onCategoryChange, onSpaceSelect, onCreateSpace, onSpaceSettings }: KnowledgeHomePageProps) {
  const localize = useLocalize();
  const menuNames = useWorkbenchMenuNames();
  const id = useId();
  const [localCategory, setLocalCategory] = useState<HomeCategory>('all');
  const category = controlledCategory ?? localCategory;
  const setCategory = (next: HomeCategory) => { setLocalCategory(next); onCategoryChange?.(next); };
  const [sort, setSort] = useState<HomeSort>('create_time');
  // Retain the canonical query keys used by the existing action hook. Complete
  // lists are sorted locally, including the merged category and creation dates.
  const lists = useKnowledgeSpaceLists({ enabled });
  const groups = useMemo(() => groupHomeSpaces(
    lists.mine.data ?? [], lists.joined.data ?? [], lists.department.data ?? [],
  ), [lists.mine.data, lists.joined.data, lists.department.data]);
  const pinnedIds = useMemo(() => groups.all.filter(({ space }) => space.isPinned).map(({ space }) => space.id), [groups]);
  const [pinOrder, setPinOrder] = useState<readonly string[]>([]);
  const stablePinOrder = useMemo(() => mergePinnedOrder(pinOrder, pinnedIds), [pinOrder, pinnedIds]);
  useEffect(() => { setPinOrder((previous) => mergePinnedOrder(previous, pinnedIds)); }, [pinnedIds]);
  const visible = useMemo(() => sortHomeSpaces(groups[category], sort, stablePinOrder), [groups, category, sort, stablePinOrder]);
  const layoutOrder = visible.map(({ space }) => space.id).join('|');
  const reduceMotion = useReducedMotion();
  const [movingSpaceId, setMovingSpaceId] = useState<string | null>(null);
  useEffect(() => {
    if (!movingSpaceId) return;
    const timer = window.setTimeout(() => setMovingSpaceId(null), 600);
    return () => window.clearTimeout(timer);
  }, [movingSpaceId]);
  const ids = useMemo(() => groups.all.map(({ space }) => space.id), [groups]);
  const permissions = useKnowledgeSpaceActions(ids);
  const [pending, setPending] = useState<Set<string>>(new Set());
  const pendingRef = useRef(new Set<string>());
  const actions = useSpaceActions({
    createdSortBy: SpaceSortType.UPDATE_TIME, joinedSortBy: SpaceSortType.UPDATE_TIME,
    departmentSortBy: SpaceSortType.UPDATE_TIME,
    createdSpaces: groups.created.map(({ space }) => space),
    joinedSpaces: groups.joined.map(({ space }) => space),
    departmentSpaces: groups.department.map(({ space }) => space),
    onSpaceSelect, onActiveSpaceUpdate: () => undefined,
  });
  const loading = lists.mine.isLoading || lists.joined.isLoading || lists.department.isLoading;
  const resolved = !loading && !lists.error;
  const refreshing = lists.mine.isFetching || lists.joined.isFetching || lists.department.isFetching;

  const handleAction = async (item: HomeSpace, action: 'pin' | 'delete') => {
    const { space, source } = item;
    if (pendingRef.current.has(space.id)) return;
    pendingRef.current.add(space.id);
    setPending(new Set(pendingRef.current));
    try {
      if (action === 'pin') {
        // Retain ranks on unpin so a failed optimistic unpin returns to its original place.
        // A new pin intent always leads, including when re-pinning a previously unpinned item.
        if (!space.isPinned) setPinOrder((previous) => [space.id, ...mergePinnedOrder(previous, pinnedIds).filter((id) => id !== space.id)]);
        setMovingSpaceId(space.id);
        await actions.handlePinSpace(space.id, !space.isPinned, source);
      }
      else await actions.handleDeleteSpace(space.id);
    } finally {
      pendingRef.current.delete(space.id);
      setPending(new Set(pendingRef.current));
    }
  };

  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next = index;
    if (event.key === 'ArrowRight') next = (index + 1) % categories.length;
    else if (event.key === 'ArrowLeft') next = (index + categories.length - 1) % categories.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = categories.length - 1;
    else return;
    event.preventDefault();
    setCategory(categories[next]);
    const nextTab = document.getElementById(`${id}-tab-${categories[next]}`);
    nextTab?.focus({ preventScroll: true });
    nextTab?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  };

  return (
    <section className={`${tokens.scope} ${styles.page}`} aria-label={menuNames.knowledge}>
      <header className={styles.header}>
        <h1 className={styles.title}>{menuNames.knowledge}</h1>
        <div className={USE_PRODUCT_COMPONENTS ? styles.productHeaderActions : styles.headerActions}>
          {USE_PRODUCT_COMPONENTS ? <ProductButton type="button" color="primary" variant="solid" size="medium"
            data-product-control disabled={!enabled} onClick={onCreateSpace}>
            <Outlined.Plus aria-hidden />{localize('com_knowledge.create_knowledge_space')}
          </ProductButton> : <button type="button" className={styles.primaryButton} disabled={!enabled} onClick={onCreateSpace}>
            <Outlined.Plus aria-hidden />{localize('com_knowledge.create_knowledge_space')}
          </button>}
        </div>
      </header>
      <div className={styles.toolbar}>
        <div className={styles.tabs} role="tablist" aria-label={menuNames.knowledge}>
          {categories.map((key, index) => (
            <button key={key} type="button" role="tab" id={`${id}-tab-${key}`}
              aria-selected={category === key} aria-controls={`${id}-panel`}
              tabIndex={category === key ? 0 : -1} className={styles.tab}
              onClick={() => setCategory(key)} onKeyDown={(event) => handleTabKeyDown(event, index)}>
              {key !== 'all' ? <img className={styles.tabIcon} src={categoryIcons[key]} alt="" /> : null}
              <span>{localize(`com_knowledge.home_next.${key}`)}{' '}
              <span>{resolved ? `(${groups[key].length})` : '—'}</span></span>
            </button>
          ))}
        </div>
        <KnowledgeHomeSort value={sort} onValueChange={setSort} />
      </div>
      <div id={`${id}-panel`} role="tabpanel" tabIndex={0}
        aria-labelledby={`${id}-tab-${category}`} aria-busy={loading || refreshing} className={styles.panel}>
        {lists.error ? (
          <div className={styles.status} role="alert">
            <p>{localize('com_knowledge.home_next.load_error')}</p>
            <button type="button" className={styles.secondaryButton} onClick={lists.retry}>{localize('com_ui_retry')}</button>
          </div>
        ) : loading ? <p className={styles.status} role="status">{localize('com_knowledge.loading')}</p>
          : visible.length === 0 ? <p className={styles.status} role="status">{localize('com_knowledge.no_data')}</p>
            : <div className={styles.grid}>
              {visible.map((item, index) => <KnowledgeHomeCard key={item.space.id} item={item}
                animateLayout={!reduceMotion} moving={movingSpaceId === item.space.id}
                layoutOrder={layoutOrder}
                layoutDelay={movingSpaceId === item.space.id ? 0 : Math.min(index * .02, .12)}
                pending={pending.has(item.space.id)} permissions={permissions.actions[item.space.id] ?? []}
                permissionsLoading={permissions.isSpaceActionsPending(item.space.id)}
                onMenuOpen={() => void permissions.ensureSpaceActions(item.space.id)}
                onSelect={onSpaceSelect}
                onEdit={() => {
                  const allowed = permissions.actions[item.space.id] ?? [];
                  if (!pending.has(item.space.id) && (allowed.includes('edit') || allowed.includes('manage_permission'))) onSpaceSettings(item.space);
                }}
                onAction={(action) => { void handleAction(item, action).catch(showApiError); }} />)}
            </div>}
      </div>
    </section>
  );
}
