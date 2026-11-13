import { KnowledgeDeletionDialog } from "./SpaceDetail/KnowledgeDeletionDialog";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useReducedMotion } from 'framer-motion';
import { Button as ProductButton, Tabs, TooltipProvider } from '@bisheng/ui';
import { MODULE_HOME_BODY, MODULE_HOME_COLUMN, MODULE_HOME_FRAME, MODULE_HOME_TOOLBAR, ModuleHomeHeader } from '~/components/ModuleHome';
import cn from '~/utils/cn';
import { USE_PRODUCT_COMPONENTS } from './home/vnext/componentMode';
import { Filled, Outlined } from 'bisheng-icons';
import { SpaceSortType, type KnowledgeSpace } from '~/api/knowledge';
import { showApiError } from '~/api/request';
import { useLocalize, useWorkbenchMenuNames } from '~/hooks';
import { useKnowledgeSpaceLists } from './hooks/useKnowledgeSpaceLists';
import { useKnowledgeSpaceActions, type KnowledgeSpaceAction } from './hooks/useKnowledgeSpacePermissions';
import { useSpaceActions } from './hooks/useSpaceActions';
import { KnowledgeHomeSort } from './home/vnext/KnowledgeHomeSort';
import { KnowledgeHomeCard } from './home/vnext/KnowledgeHomeCard';
import { KnowledgeHomeEmptyState } from './home/vnext/KnowledgeHomeEmptyState';
import { KNOWLEDGE_HOME_BATCH_SIZE, KnowledgeHomeGrid } from './home/vnext/KnowledgeHomeGrid';
import { useKnowledgeHomeSort } from './home/vnext/useKnowledgeHomeSort';
import { groupHomeSpaces, mergePinnedOrder, sortHomeSpaces, type HomeCategory, type HomeSpace } from './home/vnext/homeSpaces';
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
const categoryIcons = { department: Filled.Departure, created: Filled.Person, joined: Filled.Tag };
const EMPTY_ACTIONS: KnowledgeSpaceAction[] = [];

export function KnowledgeHomePage({ enabled = true, category: controlledCategory, onCategoryChange, onSpaceSelect, onCreateSpace, onSpaceSettings, onKnowledgeSquare }: KnowledgeHomePageProps) {
  const localize = useLocalize();
  const menuNames = useWorkbenchMenuNames();
  const tabsRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [localCategory, setLocalCategory] = useState<HomeCategory>('all');
  const category = controlledCategory ?? localCategory;
  const setCategory = (next: HomeCategory) => {
    if (controlledCategory === undefined) setLocalCategory(next);
    onCategoryChange?.(next);
  };
  useLayoutEffect(() => {
    // The shared tab strip generates trigger IDs; link the external scroll panel to them.
    const tab = tabsRef.current?.querySelector<HTMLButtonElement>('[role="tab"][aria-selected="true"]');
    const panel = panelRef.current;
    const panelId = tab?.getAttribute('aria-controls');
    if (tab && panel && panelId) {
      panel.id = panelId;
      panel.setAttribute('aria-labelledby', tab.id);
    }
  }, [category]);
  const [sort, setSort] = useKnowledgeHomeSort();
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
  const reduceMotion = useReducedMotion();
  // Layout animations measure each card before and after a reorder. Keep that
  // work bounded even when switching between a small category and All.
  const animateLayout = !reduceMotion && groups.all.length <= KNOWLEDGE_HOME_BATCH_SIZE;
  const layoutOrder = useMemo(
    () => animateLayout ? visible.map(({ space }) => space.id).join('|') : undefined,
    [animateLayout, visible],
  );
  const [movingSpaceId, setMovingSpaceId] = useState<string | null>(null);
  useEffect(() => {
    if (!movingSpaceId) return;
    const timer = window.setTimeout(() => setMovingSpaceId(null), 1100);
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
  const empty = resolved && visible.length === 0;
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
        if (animateLayout) setMovingSpaceId(space.id);
        await actions.handlePinSpace(space.id, !space.isPinned, source);
      }
      else await actions.handleDeleteSpace(space.id);
    } finally {
      pendingRef.current.delete(space.id);
      setPending(new Set(pendingRef.current));
    }
  };

  const renderCard = (item: HomeSpace, index: number) => {
    const id = item.space.id;
    const allowed = permissions.actions[id] ?? EMPTY_ACTIONS;
    const isPending = pending.has(id);
    const moving = movingSpaceId === id;
    return <KnowledgeHomeCard key={id} item={item} moving={moving} layoutOrder={layoutOrder}
      layoutDelay={animateLayout && !moving ? Math.min(index * .02, .12) : 0}
      pending={isPending} permissions={allowed} permissionsLoading={permissions.isSpaceActionsPending(id)}
      onMenuOpen={() => { void permissions.ensureSpaceActions(id); }}
      onSelect={onSpaceSelect}
      onEdit={() => {
        if (!pendingRef.current.has(id) && (allowed.includes('edit') || allowed.includes('manage_permission'))) {
          onSpaceSettings(item.space);
        }
      }}
      onAction={(action) => { void handleAction(item, action).catch(showApiError); }} />;
  };

  return (
    <section className={cn(MODULE_HOME_FRAME, tokens.scope, styles.page)} aria-label={menuNames.knowledge}>
      <ModuleHomeHeader title={menuNames.knowledge}>
        {USE_PRODUCT_COMPONENTS ? <ProductButton type="button" color="primary" variant="solid" size="medium"
          data-product-control disabled={!enabled} onClick={onCreateSpace}>
          <Outlined.Plus aria-hidden />{localize('com_knowledge.create_knowledge_space')}
        </ProductButton> : <button type="button" className={styles.primaryButton} disabled={!enabled} onClick={onCreateSpace}>
          <Outlined.Plus aria-hidden />{localize('com_knowledge.create_knowledge_space')}
        </button>}
      </ModuleHomeHeader>
      <div className={cn(MODULE_HOME_COLUMN, MODULE_HOME_TOOLBAR, styles.toolbar)}>
        <div ref={tabsRef} className={styles.productTabs}>
          <Tabs className="dsh-home-tabs" aria-label={menuNames.knowledge} size="medium" activeKey={category}
            onChange={(value) => {
              const next = categories.find((key) => key === value);
              if (next) setCategory(next);
            }}
            items={categories.map((key) => {
              const Icon = key !== 'all' ? categoryIcons[key] : undefined;
              return {
                key,
                icon: Icon ? <Icon aria-hidden /> : undefined,
                label: localize(`com_knowledge.home_next.${key}`),
                badge: resolved ? groups[key].length : undefined,
              };
            })} />
        </div>
        <KnowledgeHomeSort value={sort} onValueChange={setSort} />
      </div>
      <div ref={scrollRef} className={cn(MODULE_HOME_BODY, 'scroll-on-scroll flex min-h-0 w-full flex-1 flex-col items-center overflow-y-auto')}>
        <div ref={panelRef} role="tabpanel" tabIndex={0}
          aria-busy={loading || refreshing} className={cn(MODULE_HOME_COLUMN, styles.panel, empty && styles.emptyPanel)}>
          {lists.error ? (
            <div className={styles.status} role="alert">
              <p>{localize('com_knowledge.home_next.load_error')}</p>
              <button type="button" className={styles.secondaryButton} onClick={lists.retry}>{localize('com_ui_retry')}</button>
            </div>
          ) : loading ? <p className={styles.status} role="status">{localize('com_knowledge.loading')}</p>
            : empty ? <KnowledgeHomeEmptyState category={category}
              onCreate={enabled ? onCreateSpace : undefined}
              onOpenSquare={enabled ? onKnowledgeSquare : undefined} />
              : groups.all.length > KNOWLEDGE_HOME_BATCH_SIZE
                ? <KnowledgeHomeGrid key={`${category}:${sort}`} items={visible} renderCard={renderCard} scrollRef={scrollRef} />
                : <TooltipProvider><div className={styles.grid}>{visible.map(renderCard)}</div></TooltipProvider>}
        </div>
      </div>
      <KnowledgeDeletionDialog operation={actions.deletion} />
    </section>
  );
}
