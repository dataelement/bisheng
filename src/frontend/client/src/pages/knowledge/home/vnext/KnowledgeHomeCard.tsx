import { Outlined } from 'bisheng-icons';
import { Dropdown, DropdownItem } from '@bisheng/ui';
import { USE_PRODUCT_COMPONENTS } from './componentMode';
import * as Menu from '@radix-ui/react-dropdown-menu';
import { motion } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getSpaceInfoApi } from '~/api/knowledge';
import type { KnowledgeSpace } from '~/api/knowledge';
import { showApiError } from '~/api/request';
import { useLocalize } from '~/hooks';
import { useConfirm } from '~/Providers';
import { isDemoId } from '~/mock/demo/ids';
import type { KnowledgeSpaceAction } from '../../hooks/useKnowledgeSpacePermissions';
import { homeTimestamp, type HomeSpace } from './homeSpaces';
import departmentIcon from './assets/card-1.png';
import createdIcon from './assets/card-2.png';
import joinedIcon from './assets/card-3.png';
import pinnedIcon from './assets/Clip.svg';
import unpinnedIcon from './assets/clip-2.svg';
import unpinnedHoverIcon from './assets/clip-2-hover.svg';
import memberIcon from './assets/menber.svg';
import moreIcon from './assets/more.svg';
import tokens from './tokens.module.css';
import styles from './KnowledgeHomeNext.module.css';

const spaceIcons = { department: departmentIcon, created: createdIcon, joined: joinedIcon };

interface KnowledgeHomeCardProps {
  animateLayout: boolean;
  moving: boolean;
  layoutDelay: number;
  layoutOrder: string;
  item: HomeSpace;
  pending: boolean;
  permissions: KnowledgeSpaceAction[];
  permissionsLoading: boolean;
  onMenuOpen: () => void;
  onSelect: (space: KnowledgeSpace) => void;
  onAction: (action: 'pin' | 'delete') => void;
  onEdit: () => void;
}

export function KnowledgeHomeCard({ animateLayout, moving, layoutDelay, layoutOrder, item, pending, permissions, permissionsLoading, onMenuOpen, onSelect, onAction, onEdit }: KnowledgeHomeCardProps) {
  const localize = useLocalize();
  const confirm = useConfirm();
  const { space, source } = item;
  const canEdit = permissions.includes('edit') || permissions.includes('manage_permission');
  const canDelete = permissions.includes('delete');
  const demo = isDemoId(space.id);
  const cardRef = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!cardRef.current || space.creator?.trim() || !space.creatorId || demo) return;
    if (typeof IntersectionObserver === 'undefined') { setVisible(true); return; }
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) { setVisible(true); observer.disconnect(); }
    });
    observer.observe(cardRef.current);
    return () => observer.disconnect();
  }, [space.creator, space.creatorId, demo]);
  const creatorInfo = useQuery({
    queryKey: ['knowledgeHomeCreator', space.id, space.creatorId],
    queryFn: () => getSpaceInfoApi(space.id),
    enabled: visible && !demo && !!space.creatorId && !space.creator?.trim(),
    staleTime: 5 * 60 * 1000,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const owner = space.creator?.trim() || creatorInfo.data?.creator?.trim();
  const updated = homeTimestamp(space.updatedAt);
  const pinLabel = localize(space.isPinned ? 'com_knowledge.unpin' : 'com_knowledge.pin_space');
  // Category artwork follows the confirmed API source, including in the merged tab.
  const icon = spaceIcons[source];

  const handleRemove = async () => {
    if (!canDelete || pending || demo) return;
    const ok = await confirm({
      description: `${localize('com_knowledge.confirm_delete_space')}${localize('com_knowledge.delete_irreversible_warning')}`,
      variant: 'destructive',
    });
    if (ok) onAction('delete');
  };

  return (
    <motion.article ref={cardRef} className={styles.card} aria-busy={pending} layout={animateLayout ? 'position' : false}
      layoutDependency={layoutOrder}
      initial={false} style={{ zIndex: moving ? 2 : 0 }}
      transition={{ layout: { duration: .6, delay: layoutDelay, ease: [.22, 1, .36, 1] } }}>
      <div className={styles.cardHeading}>
        <img className={styles.spaceIcon} src={icon} width={36} height={36} alt="" />
        <h2 className={styles.cardTitle}>
          <button type="button" className={styles.openSpace} title={space.name} onClick={() => onSelect(space)}>
            {space.name}
          </button>
        </h2>
        <button type="button" className={`${styles.iconButton} ${styles.pinButton}`} aria-label={pinLabel} title={pinLabel}
          aria-pressed={space.isPinned} disabled={pending || demo} onClick={() => onAction('pin')}>
          <span className={styles.pinGlyph} aria-hidden="true">
            <img className={space.isPinned ? undefined : styles.pinDefault} src={space.isPinned ? pinnedIcon : unpinnedIcon}
              width={20} height={20} alt="" />
            {!space.isPinned ? <img className={styles.pinHover} src={unpinnedHoverIcon} width={20} height={20} alt="" /> : null}
          </span>
        </button>
      </div>
      <p className={`${styles.description} ${space.description?.trim() ? '' : styles.emptyDescription}`} title={space.description || undefined}>
        {space.description?.trim() || localize('com_knowledge.home_next.no_description')}
      </p>
      <footer className={styles.cardFooter}>
        <span className={styles.owner} title={owner}>
          {owner ? <><img src={memberIcon} width={16} height={16} alt="" /><span>{owner}</span></> : null}
        </span>
        {updated ? <time dateTime={new Date(updated).toISOString()} className={styles.updated}>
          {localize('com_knowledge.home_next.updated_at', { date: new Intl.DateTimeFormat(undefined, {
            year: 'numeric', month: '2-digit', day: '2-digit',
          }).format(new Date(updated)) })}
        </time> : null}
        {USE_PRODUCT_COMPONENTS ? <Dropdown align="end" panelClassName={`${tokens.geometry} ${styles.productMenu}`}
          onOpenChange={(open) => { if (open) onMenuOpen(); }}
          menu={permissionsLoading ? <DropdownItem disabled>{localize('com_knowledge.loading')}</DropdownItem> : <>
            {canEdit ? <DropdownItem icon={<Outlined.Edit />} disabled={pending} onSelect={onEdit}>{localize('com_knowledge.space_settings')}</DropdownItem> : null}
            {canDelete ? <DropdownItem icon={<Outlined.Delete />} danger disabled={pending} onSelect={() => { void handleRemove().catch(showApiError); }}>{localize('com_knowledge.delete_space')}</DropdownItem> : null}
            {!canEdit && !canDelete ? <DropdownItem disabled>{localize('com_knowledge.home_next.no_actions')}</DropdownItem> : null}
          </>}>
          <button type="button" className={`${styles.iconButton} ${styles.moreButton}`} aria-label={localize('com_knowledge.home_next.more')} disabled={pending || demo}>
            <span className={styles.moreGlyph} aria-hidden="true"><img src={moreIcon} width={20} height={20} alt="" /></span>
          </button>
        </Dropdown> : <Menu.Root onOpenChange={(open) => { if (open) onMenuOpen(); }}>
          <Menu.Trigger asChild>
            <button type="button" className={`${styles.iconButton} ${styles.moreButton}`} aria-label={localize('com_knowledge.home_next.more')}
              disabled={pending || demo}>
              <span className={styles.moreGlyph} aria-hidden="true">
                <img src={moreIcon} width={20} height={20} alt="" />
              </span>
            </button>
          </Menu.Trigger>
          <Menu.Portal>
            <Menu.Content align="end" sideOffset={4} collisionPadding={8} className={`${tokens.scope} ${styles.menu}`}>
              {permissionsLoading ? <Menu.Item disabled className={styles.menuItem}>{localize('com_knowledge.loading')}</Menu.Item>
                : <>
                  {canEdit ? <Menu.Item className={styles.menuItem} disabled={pending} onSelect={onEdit}><Outlined.Edit aria-hidden />{localize('com_knowledge.space_settings')}</Menu.Item> : null}
                  {canDelete ? <Menu.Item className={styles.menuItem} disabled={pending}
                    onSelect={() => { void handleRemove().catch(showApiError); }}>
                    <Outlined.Delete aria-hidden />{localize('com_knowledge.delete_space')}
                  </Menu.Item> : null}
                  {!canEdit && !canDelete ? <Menu.Item disabled className={styles.menuItem}>
                    {localize('com_knowledge.home_next.no_actions')}
                  </Menu.Item> : null}
                </>}

            </Menu.Content>
          </Menu.Portal>
        </Menu.Root>}
      </footer>
    </motion.article>
  );
}
