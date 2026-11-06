import { Select } from '@bisheng/ui';
import { useLocalize } from '~/hooks';
import type { HomeSort } from './homeSpaces';
import styles from './KnowledgeHomeNext.module.css';

interface KnowledgeHomeSortProps {
  value: HomeSort;
  onValueChange: (value: HomeSort) => void;
}

const orders: HomeSort[] = ['create_time', 'update_time', 'name'];

export function KnowledgeHomeSort({ value, onValueChange }: KnowledgeHomeSortProps) {
  const localize = useLocalize();
  return (
    <div className={styles.sort}>
      <Select
        size="medium"
        variant="ghost"
        aria-label={localize('com_knowledge.sort_field')}
        value={value}
        options={orders.map((order) => ({ value: order, label: localize(`com_knowledge.home_next.sort_${order}`) }))}
        onChange={(next) => {
          const order = orders.find((order) => order === next);
          if (order) onValueChange(order);
        }}
      />
    </div>
  );
}
