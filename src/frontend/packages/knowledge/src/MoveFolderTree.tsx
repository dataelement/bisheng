import { Button, TreeNavigationNode, TreeNavigationStatus } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { MoveDestinationServices, MoveFolder, MoveTarget } from './moveTypes';
import { useMoveResource } from './useMoveResource';

interface MoveFolderTreeProps {
  spaceId: string;
  parentId?: string | null;
  depth?: number;
  selection: MoveTarget | null;
  services: MoveDestinationServices;
  onSelect: (folder: MoveFolder) => void;
  onError: (error: unknown) => void;
}

function FolderNode({ folder, ...props }: MoveFolderTreeProps & { folder: MoveFolder }) {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.move' });
  const [expanded, setExpanded] = useState(false);
  const [visited, setVisited] = useState(false);
  const selected = props.selection?.spaceId === props.spaceId && props.selection.folderId === folder.id;
  return (
    <TreeNavigationNode
      name={folder.name}
      depth={props.depth ?? 1}
      icon={<Outlined.FolderClose />}
      current={selected && 'location'}
      onSelect={() => props.onSelect(folder)}
      disclosure={{
        expanded,
        label: t(expanded ? 'collapse' : 'expand', { name: folder.name }),
        onToggle: () => { setExpanded((value) => !value); setVisited(true); },
      }}
    >
      {visited && <MoveFolderTree {...props} parentId={folder.id} depth={(props.depth ?? 1) + 1} />}
    </TreeNavigationNode>
  );
}

export function MoveFolderTree({ parentId = null, depth = 1, ...props }: MoveFolderTreeProps) {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.move' });
  const { services, spaceId, onError } = props;
  const load = useCallback((signal: AbortSignal) => services.listFolders(spaceId, parentId, signal), [services, spaceId, parentId]);
  const resource = useMoveResource(load, onError);
  if (resource.loading) return <TreeNavigationStatus depth={depth} loading>{t('loading')}</TreeNavigationStatus>;
  if (resource.error) return <TreeNavigationStatus depth={depth}>
    {t('load_failed')} <Button variant="text" size="small" onClick={resource.retry}>{t('retry')}</Button>
  </TreeNavigationStatus>;
  return <>{resource.data?.map((folder) => <FolderNode key={folder.id} {...props} folder={folder} depth={depth} />)}</>;
}
