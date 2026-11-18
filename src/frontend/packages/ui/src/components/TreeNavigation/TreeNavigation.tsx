import { Outlined } from 'bisheng-icons';
import { forwardRef, useId, useRef, type ComponentProps, type ComponentPropsWithoutRef, type CSSProperties, type ReactNode } from 'react';
import cn from '../../utils/cn';
import { useLoadingIndicatorRenderer } from '../../providers/LoadingIndicatorProvider';
import { Dropdown } from '../Dropdown';
import styles from './TreeNavigation.module.css';
import { useTreeViewport } from './useTreeViewport';

export interface TreeNavigationProps extends Omit<ComponentProps<'nav'>, 'aria-label'> {
  'aria-label': string;
  size?: 'small' | 'medium';
  /** Draw vertical guides alongside expanded branches. */
  showLine?: boolean;
  /** Stable value changed by the caller to reveal the same current node again. */
  revealKey?: string | number;
}

export function TreeNavigation({ children, className, size = 'small', showLine = false, revealKey, ...props }: TreeNavigationProps) {
  const viewportRef = useRef<HTMLElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  useTreeViewport(viewportRef, contentRef, revealKey);

  return (
    <nav {...props} ref={viewportRef} tabIndex={0} className={cn(styles.viewport, className)} data-size={size} data-show-line={showLine}>
      <div ref={contentRef} className={styles.content}>{children}</div>
    </nav>
  );
}

export function TreeNavigationList({ className, ...props }: ComponentProps<'ul'>) {
  return <ul {...props} className={cn(styles.list, className)} />;
}

export interface TreeNavigationGroupProps {
  label: string;
  expanded: boolean;
  onToggle: () => void;
  actions?: ReactNode;
  children: ReactNode;
}

export function TreeNavigationGroup({ label, expanded, onToggle, actions, children }: TreeNavigationGroupProps) {
  const id = useId();
  return (
    <section className={styles.group} aria-labelledby={`${id}-label`} data-tree-group="">
      <div className={styles.groupHeader} data-tree-group-header="">
        <button type="button" className={styles.groupToggle} aria-expanded={expanded} aria-controls={id} data-tree-group-toggle="" onClick={onToggle}>
          <span id={`${id}-label`} className="truncate" title={label}>{label}</span>
          {expanded ? <Outlined.Down aria-hidden /> : <Outlined.Right aria-hidden />}
        </button>
        {actions}
      </div>
      <div id={id} className={styles.groupBody} hidden={!expanded}>{expanded && children}</div>
    </section>
  );
}

export interface TreeNavigationGroupActionProps extends Omit<ComponentPropsWithoutRef<'button'>, 'aria-label' | 'type'> {
  'aria-label': string;
}

export const TreeNavigationGroupAction = forwardRef<HTMLButtonElement, TreeNavigationGroupActionProps>(
  function TreeNavigationGroupAction({ className, ...props }, ref) {
    return <button {...props} ref={ref} type="button" className={cn(styles.groupAction, className)} />;
  },
);

export interface TreeNavigationNodeProps {
  name: string;
  depth?: number;
  icon: ReactNode;
  /** Display-only content adjacent to the name. */
  marker?: ReactNode;
  current?: boolean | 'page' | 'location';
  disabled?: boolean;
  href?: string;
  onSelect?: () => void;
  disclosure?: { expanded: boolean; label: string; onToggle: () => void };
  hideLeafArrow?: boolean;
  actions?: ReactNode;
  /** Child list items, including any branch loading, error or pagination state. */
  children?: ReactNode;
}

export function TreeNavigationNode({
  name, depth = 0, icon, marker, current, disabled, href, onSelect, disclosure, hideLeafArrow, actions, children,
}: TreeNavigationNodeProps) {
  const id = useId();
  const expanded = disclosure?.expanded ?? true;
  const targetProps = {
    'aria-current': current || undefined,
    'data-tree-target': '',
    className: styles.target,
    onClick: onSelect,
    title: name,
  };
  const targetContent = (
    <>
      <span className={styles.iconSlot} aria-hidden>{icon}</span>
      <span className={styles.nameSlot}>
        {/* The hidden copy gives the row the width needed to scroll to the end of the name. */}
        <span className={styles.intrinsicName} aria-hidden="true"><span>{name}</span>{marker}</span>
        <span className={styles.visibleName} data-tree-name=""><span>{name}</span>{marker}</span>
      </span>
    </>
  );

  return (
    <li data-tree-node="" style={{ '--tree-depth': depth } as CSSProperties}>
      <div
        className={styles.row}
        data-tree-row=""
        data-current={Boolean(current)}
        data-actions={actions ? '' : undefined}
      >
        {disclosure ? (
          <button type="button" className={styles.disclosure} data-tree-disclosure="" aria-label={disclosure.label}
            aria-expanded={expanded} aria-controls={id} onClick={disclosure.onToggle}>
            {expanded ? <Outlined.Down aria-hidden /> : <Outlined.Right aria-hidden />}
          </button>
        ) : <span className={styles.disclosure} aria-hidden>{!hideLeafArrow && <Outlined.Right />}</span>}
        {href && !disabled
          ? <a {...targetProps} href={href}>{targetContent}</a>
          : <button {...targetProps} type="button" disabled={disabled}>{targetContent}</button>}
        {actions && <div className={styles.rowActions}>{actions}</div>}
      </div>
      {(disclosure || children) && (
        <TreeNavigationList id={id} hidden={!expanded || !children}>{expanded && children}</TreeNavigationList>
      )}
    </li>
  );
}

export interface TreeNavigationMenuProps extends Pick<ComponentProps<typeof Dropdown>, 'menu' | 'onOpenChange' | 'onCloseAutoFocus' | 'disabled'> {
  label: string;
}

export function TreeNavigationMenu({ label, ...props }: TreeNavigationMenuProps) {
  return (
    <Dropdown {...props} align="end">
      <button type="button" className={styles.menuTrigger} aria-label={label} data-tree-menu="">
        <Outlined.More aria-hidden />
      </button>
    </Dropdown>
  );
}

export interface TreeNavigationStatusProps {
  children: ReactNode;
  depth?: number;
  loading?: boolean;
}

export function TreeNavigationStatus({ children, depth = 0, loading }: TreeNavigationStatusProps) {
  const renderIndicator = useLoadingIndicatorRenderer();
  return (
    <li className={styles.status} style={{ '--tree-depth': depth } as CSSProperties}>
      {loading ? <span role="status" className="flex items-center gap-1">
        {renderIndicator ? <>
          <span className="inline-flex shrink-0" aria-hidden>{renderIndicator({ className: 'size-4' })}</span>
          <span className="sr-only">{children}</span>
        </> : <>
          <Outlined.Loading aria-hidden className="size-4 shrink-0 animate-spin motion-reduce:animate-none" />
          {children}
        </>}
      </span> : children}
    </li>
  );
}
