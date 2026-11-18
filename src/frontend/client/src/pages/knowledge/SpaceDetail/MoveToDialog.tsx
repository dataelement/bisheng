import { MoveToDialog as SharedMoveToDialog, type MoveToDialogProps as SharedMoveToDialogProps } from '@bisheng/knowledge';
import { moveDestinationServices } from '~/api/knowledgeMoveDestinations';
import { showApiError } from '~/api/request';

interface MoveToDialogProps extends Omit<SharedMoveToDialogProps, 'services' | 'onError'> {
  currentSpaceName: string;
}

export function MoveToDialog(props: MoveToDialogProps) {
  return <SharedMoveToDialog {...props} services={moveDestinationServices} onError={showApiError} />;
}
