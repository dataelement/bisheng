import { Button, Dropdown, DropdownItem, Tooltip } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { showApiError } from '~/api/request';
import { useLocalize } from '~/hooks';
import type { KnowledgeSpaceAction } from '../../hooks/useKnowledgeSpacePermissions';
import styles from './KnowledgeHomeCard.module.css';

interface KnowledgeHomeCardMenuProps {
  disabled: boolean;
  permissions: KnowledgeSpaceAction[];
  permissionsLoading: boolean;
  onOpen: () => void;
  onEdit: () => void;
  onDelete: () => void;
  canLeave: boolean;
  allowDelete: boolean;
  onLeave: () => void;
}

export function KnowledgeHomeCardMenu({
  disabled, permissions, permissionsLoading, onOpen, onEdit, onDelete, canLeave, allowDelete, onLeave,
}: KnowledgeHomeCardMenuProps) {
  const localize = useLocalize();
  const canEdit = permissions.includes('edit') || permissions.includes('manage_permission');
  const canDelete = allowDelete && !canLeave && permissions.includes('delete');
  const moreLabel = localize('com_knowledge.home_next.more');

  const handleDelete = async () => {
    if (!canDelete || disabled) return;
    onDelete();
  };

  const menu = permissionsLoading ? (
    <DropdownItem disabled>{localize('com_knowledge.loading')}</DropdownItem>
  ) : (
    <>
      {canEdit && (
        <DropdownItem icon={<Outlined.Edit />} disabled={disabled} onSelect={onEdit}>
          {localize('com_knowledge.space_settings')}
        </DropdownItem>
      )}
      {canDelete && (
        <DropdownItem icon={<Outlined.Delete />} danger disabled={disabled}
          onSelect={() => { void handleDelete().catch(showApiError); }}>
          {localize('com_knowledge.delete_space')}
        </DropdownItem>
      )}
      {canLeave && (
        <DropdownItem icon={<Outlined.LogOut />} danger disabled={disabled} onSelect={onLeave}>
          {localize('com_knowledge.exit_space_short')}
        </DropdownItem>
      )}
      {!canEdit && !canDelete && !canLeave && (
        <DropdownItem disabled>{localize('com_knowledge.home_next.no_actions')}</DropdownItem>
      )}
    </>
  );

  return (
    <Tooltip content={moreLabel}>
      <span className={styles.cardMenu}>
        <Dropdown align="end" menu={menu}
          onOpenChange={(open) => { if (open) onOpen(); }}>
          <Button type="button" color="default" variant="text" size="small" iconOnly
            data-product-control aria-label={moreLabel} disabled={disabled}
            icon={<Outlined.More aria-hidden />} />
        </Dropdown>
      </span>
    </Tooltip>
  );
}
