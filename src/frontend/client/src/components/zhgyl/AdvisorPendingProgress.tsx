import { useLocalize } from '~/hooks';
import { createBusinessTimeline } from './businessTimeline';
import { BusinessProcessCard } from './BusinessProcessCard';
import type { AdvisorScene } from './scenes';

export function AdvisorPendingProgress({ scene, messageId }: { scene: AdvisorScene; messageId: string }) {
  const t = useLocalize();
  const state = createBusinessTimeline(t).make(scene, `pending-${messageId}`);
  state.nodes[0].summary = t('zhgyl.flowCopy.submitting');
  return <BusinessProcessCard state={state} live />;
}
