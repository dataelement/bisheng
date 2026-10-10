import { StateView } from '@bisheng/ui';
import { EmptyStateIllustration, NoPermissionIllustration } from '~/components/illustrations';
import { useLocalize } from '~/hooks';
import type { GuestAccessState } from '../guestAccessError';

type BlockedState = Exclude<GuestAccessState, 'loading' | 'ok'>;

interface GuestAppUnavailableProps {
  state: BlockedState;
}

/**
 * What a share-link visitor sees when the link resolves to nothing usable.
 *
 * There is deliberately no button. A guest has nowhere to go: no sign-in, no
 * home page, and refreshing will not bring an offline app back — a retry
 * control would only invite repeated clicking. The way forward is a sentence,
 * and it always points at the person who sent the link.
 */
export function GuestAppUnavailable({ state }: GuestAppUnavailableProps) {
  const localize = useLocalize();

  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <StateView
        size="page"
        image={state === 'closed' ? <NoPermissionIllustration /> : <EmptyStateIllustration />}
        title={localize(`com_guest_app_unavailable.${state}_title`)}
        description={localize(`com_guest_app_unavailable.${state}_desc`)}
      />
    </div>
  );
}
