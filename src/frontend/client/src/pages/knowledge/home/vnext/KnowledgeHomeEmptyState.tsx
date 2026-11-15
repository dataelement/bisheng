import { Button, EmptyStateIllustration, StateView } from '@bisheng/ui';
import { Trans } from 'react-i18next';
import { useLocalize } from '~/hooks';
import cn from '~/utils/cn';
import type { HomeCategory } from './homeSpaces';
import styles from './KnowledgeHomeNext.module.css';

interface KnowledgeHomeEmptyStateProps {
  category: HomeCategory;
  onCreate?: () => void;
  onOpenSquare?: () => void;
}

export function KnowledgeHomeEmptyState({ category, onCreate, onOpenSquare }: KnowledgeHomeEmptyStateProps) {
  const localize = useLocalize();
  const message = localize(category === 'all' || category === 'department'
    ? `com_knowledge.home_next.empty_${category}`
    : 'com_knowledge.home_next.empty_content');
  const onAction = category === 'created' ? onCreate : category === 'joined' ? onOpenSquare : undefined;

  return (
    <>
      <StateView size="page" className={cn(styles.emptyFull, 'min-h-0')}
        image={<EmptyStateIllustration />}
        title={<span role="status">{onAction ? (
          <Trans i18nKey={`com_knowledge.home_next.empty_${category}`} components={{
            cta: <Button type="button" color="primary" variant="link" size="small" data-product-control onClick={onAction} />,
          }} />
        ) : message}</span>} />
      <StateView size="inline" className={cn(styles.emptyCompact, 'h-full')} title={message} />
    </>
  );
}
