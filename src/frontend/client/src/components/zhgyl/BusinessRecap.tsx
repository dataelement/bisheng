import { useLocalize } from '~/hooks';
import type { RecapRead } from './recapProtocol';
import { historicalProcess } from './processPresentation';
import { BusinessProcessCard } from './BusinessProcessCard';

export function BusinessRecap({ result }: { result: Exclude<RecapRead, { kind: 'other' }> }) {
  const t = useLocalize();
  if (result.kind === 'pending') return null;
  if (result.kind === 'invalid') return <span role="status" className="zh-process-status zh-historical-process">{t('zhgyl.recapInvalid')}</span>;
  return <BusinessProcessCard state={historicalProcess(result.record)} />;
}
