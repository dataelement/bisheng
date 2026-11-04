import { Tag } from '@bisheng/ui';
import { useLocalize } from '~/hooks';
import { isDemoId } from './ids';

interface DemoTagProps {
  id: unknown;
  className?: string;
}

/** Marks a DEV sample row (see ./index.ts) so it is obvious which cards cannot be opened.
 *  Renders nothing for real rows — and sample rows never exist outside DEV. */
export function DemoTag({ id, className }: DemoTagProps) {
  const localize = useLocalize();
  if (!isDemoId(id)) return null;
  return (
    <Tag size="small" color="warning" className={className}>
      {localize('com_demo_data.tag')}
    </Tag>
  );
}
