import { Outlined } from 'bisheng-icons';
import { motion } from 'framer-motion';
import { useId, type MouseEvent } from 'react';
import { Link, useLocation } from 'react-router-dom';
import type { KnowledgeSpace } from '~/api/knowledge';
import { useLocalize } from '~/hooks';
import { isDemoId } from '~/mock/demo/ids';
import cn from '~/utils/cn';
import type { KnowledgeSpaceAction } from '../../hooks/useKnowledgeSpacePermissions';
import { knowledgePathWithTab } from '../../knowledgeListNavigation';
import { KnowledgeSpaceCategoryIcon } from '../../KnowledgeSpaceCategoryIcon';
import { homeTimestamp, type HomeSpace } from './homeSpaces';
import { KnowledgeHomeCardMenu } from './KnowledgeHomeCardMenu';
import { useKnowledgeHomeCardCreator } from './useKnowledgeHomeCardCreator';
import styles from './KnowledgeHomeCard.module.css';

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

export function KnowledgeHomeCard({
  animateLayout, moving, layoutDelay, layoutOrder, item, pending,
  permissions, permissionsLoading, onMenuOpen, onSelect, onAction, onEdit,
}: KnowledgeHomeCardProps) {
  const localize = useLocalize();
  const location = useLocation();
  const titleId = useId();
  const { space, source } = item;
  const { cardRef, creator } = useKnowledgeHomeCardCreator(space);
  const demo = isDemoId(space.id);
  const disabled = pending || demo;
  const description = space.description?.trim();
  const updatedTimestamp = homeTimestamp(space.updatedAt);
  const updated = updatedTimestamp ? new Date(updatedTimestamp) : null;
  const pinLabel = localize(space.isPinned ? 'com_knowledge.unpin' : 'com_knowledge.pin_space');
  const to = demo
    ? `${location.pathname}${location.search}`
    : knowledgePathWithTab(`/knowledge/space/${space.id}`, location.search);

  const handleSelect = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.defaultPrevented) return;
    if (!demo && (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)) return;
    // Preserve native new-tab behavior; ordinary clicks use the existing detail loader.
    event.preventDefault();
    onSelect(space);
  };

  return (
    <motion.article ref={cardRef} className={styles.card} aria-busy={pending}
      layout={animateLayout ? 'position' : false} layoutDependency={layoutOrder}
      initial={false} style={{ zIndex: moving ? 2 : 0 }}
      transition={{ layout: { duration: .6, delay: layoutDelay, ease: [.22, 1, .36, 1] } }}>
      <Link className={styles.cardLink} to={to} aria-labelledby={titleId} onClick={handleSelect}>
        <div className={styles.cardHeading}>
          <KnowledgeSpaceCategoryIcon source={source} className={styles.spaceIcon} size={36} />
          <h2 id={titleId} className={styles.cardTitle} title={space.name}>{space.name}</h2>
        </div>
        <p className={cn(styles.description, !description && styles.emptyDescription)} title={description}>
          {description || localize('com_knowledge.home_next.no_description')}
        </p>
        <footer className={`${styles.cardFooter} text-caption`}>
          <span className={styles.owner} title={creator}>
            {creator && <><Outlined.People size={14} className="shrink-0" aria-hidden /><span>{creator}</span></>}
          </span>
          {updated && (
            <time dateTime={updated.toISOString()} className={styles.updated}>
              {localize('com_knowledge.home_next.updated_at', {
                date: new Intl.DateTimeFormat(undefined, {
                  year: 'numeric', month: '2-digit', day: '2-digit',
                }).format(updated),
              })}
            </time>
          )}
        </footer>
      </Link>
      <button type="button" className={styles.pinButton} aria-label={pinLabel} title={pinLabel}
        aria-pressed={space.isPinned} disabled={disabled} onClick={() => onAction('pin')}>
        <span className={styles.pinGlyph} aria-hidden="true">
          <span className={space.isPinned ? styles.pinFilled : styles.pinDefault} />
          {!space.isPinned && <span className={styles.pinHover} />}
        </span>
      </button>
      <KnowledgeHomeCardMenu disabled={disabled} permissions={permissions}
        permissionsLoading={permissionsLoading} onOpen={onMenuOpen} onEdit={onEdit}
        onDelete={() => onAction('delete')} />
    </motion.article>
  );
}
