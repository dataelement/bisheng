import { EmptyStateIllustration, StateView } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { Trans } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useLocalize } from '~/hooks';

interface AppEmptyStateProps {
  searching: boolean;
}

export function AppEmptyState({ searching }: AppEmptyStateProps) {
  const localize = useLocalize();
  return (
    <StateView
      size="page"
      className="flex-1"
      image={<EmptyStateIllustration />}
      title={<span role="status">{localize(searching ? 'com_app.search_empty_title' : 'com_app.empty_title')}</span>}
      description={searching ? localize('com_app.search_empty_description') : (
        <Trans
          i18nKey="com_app.explore_plaza"
          components={{
            cta: <Link to="/apps/explore" className="inline-flex items-center gap-0.5 text-blue-500 hover:text-blue-600" />,
            arrow: <Outlined.ArrowRight aria-hidden className="size-3.5 shrink-0" />,
          }}
        />
      )}
    />
  );
}
