import { HoverCardPortal, HoverCardContent } from '~/components/ui';
import styles from './styles.module.css';

type TPluginTooltipProps = {
  content: string;
  position: 'top' | 'bottom' | 'left' | 'right';
};

function PluginTooltip({ content, position }: TPluginTooltipProps) {
  return (
    <HoverCardPortal>
      <HoverCardContent side={position} className="w-80 ">
        <div className="space-y-2">
          <div className="text-sm text-gray-600 dark:text-gray-300">
            <div className={styles.tooltipHtml} dangerouslySetInnerHTML={{ __html: content }} />
          </div>
        </div>
      </HoverCardContent>
    </HoverCardPortal>
  );
}

export default PluginTooltip;
