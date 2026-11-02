import { useLayoutEffect, useRef, useState } from 'react';
import { Select as ProductSelect, Tooltip } from '@bisheng/ui';
import * as Select from '@radix-ui/react-select';
import { useLocalize } from '~/hooks';
import { USE_PRODUCT_COMPONENTS } from './componentMode';
import type { HomeSort } from './homeSpaces';
import arrow from './assets/sort-arrow.svg';
import tokens from './tokens.module.css';
import styles from './KnowledgeHomeNext.module.css';

interface KnowledgeHomeSortProps {
  value: HomeSort;
  onValueChange: (value: HomeSort) => void;
}

const orders: HomeSort[] = ['create_time', 'update_time', 'name'];

function SortOption({ order, label }: { order: HomeSort; label: string }) {
  const textRef = useRef<HTMLSpanElement>(null);
  const [clipped, setClipped] = useState(false);
  useLayoutEffect(() => {
    const node = textRef.current;
    if (!node) return;
    const measure = () => setClipped(node.scrollWidth > node.clientWidth);
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [label]);
  return <Tooltip content={label} disabled={!clipped} side="left">
    <Select.Item value={order} className={`${styles.menuItem} ${styles.sortItem}`}>
      <Select.ItemText><span ref={textRef} className={styles.sortOptionLabel}>{label}</span></Select.ItemText>
    </Select.Item>
  </Tooltip>;
}

export function KnowledgeHomeSort({ value, onValueChange }: KnowledgeHomeSortProps) {
  const localize = useLocalize();
  if (USE_PRODUCT_COMPONENTS) return <div className={styles.sort}>
    <ProductSelect size="medium" variant="outlined" className="w-32" aria-label={localize('com_knowledge.sort_field')}
      value={value} options={orders.map((order) => ({ value: order, label: localize(`com_knowledge.home_next.sort_${order}`) }))}
      onChange={(next) => { const order = orders.find((order) => order === next); if (order) onValueChange(order); }} />
  </div>;
  return (
    <div className={styles.sort}>
      <Select.Root value={value} onValueChange={(next) => {
        const order = orders.find((order) => order === next);
        if (order) onValueChange(order);
      }}>
        <Select.Trigger className={styles.sortTrigger} aria-label={localize('com_knowledge.sort_field')}>
          <Select.Value><span className={styles.sortValue}>{localize(`com_knowledge.home_next.sort_${value}`)}</span></Select.Value>
          <Select.Icon asChild><img src={arrow} width={8} height={4} alt="" /></Select.Icon>
        </Select.Trigger>
        <Select.Portal>
          <Select.Content position="popper" sideOffset={4} collisionPadding={8}
            className={`${tokens.scope} ${styles.menu} ${styles.sortMenu}`}>
            <Select.Viewport>
              {orders.map((order) => (
                <SortOption key={order} order={order} label={localize(`com_knowledge.home_next.sort_${order}`)} />
              ))}
            </Select.Viewport>
          </Select.Content>
        </Select.Portal>
      </Select.Root>
    </div>
  );
}
