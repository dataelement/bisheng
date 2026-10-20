import { Input, type InputProps, Button } from '@bisheng/ui';
import * as React from 'react';
import { CircleMinus, CirclePlus } from 'lucide-react';
import { useTranslation } from 'react-i18next';


import { cname, generateUUID } from '@/components/bs-ui/utils';

interface InputEntry { key: string; value: string }
interface InputListChange { action: 'u' | 'd'; id: string; value: string }
interface InputListProps extends Omit<InputProps, 'value' | 'defaultValue' | 'onChange'> {
    rules?: unknown[];
    dict?: boolean;
    value?: string[] | InputEntry[];
    defaultValue?: string[] | InputEntry[];
    inputClassName?: string;
    onChange?: (values: string[] | InputEntry[], info?: InputListChange) => void;
}

const EMPTY_VALUES: string[] = [];

export const InputList = React.forwardRef<HTMLDivElement, InputListProps>(function InputList(
    { rules: _rules, className, dict = false, inputClassName, value, defaultValue = EMPTY_VALUES, onChange, ...props }, ref,
) {
    void _rules;
    const { t } = useTranslation('bs');
    const values = value ?? defaultValue;
    const [rows, setRows] = React.useState<InputEntry[]>(() => values.map((item) =>
        typeof item === 'string' ? { key: generateUUID(6), value: item } : item));
    React.useEffect(() => {
        if (dict) return;
        setRows((previous) => values.map((item, index) => {
            const text = typeof item === 'string' ? item : item.value;
            return previous[index]?.value === text ? previous[index] : { key: generateUUID(6), value: text };
        }));
    }, [dict, values]);

    const emit = (next: InputEntry[], info?: InputListChange) => {
        setRows(next);
        onChange?.(dict ? next : next.map((row) => row.value), info);
    };
    return <div ref={ref} className={className}>
        {rows.map((row, index) => <div key={row.key} className="relative mb-2">
            <Input {...props} defaultValue={row.value} onChange={(event) => {
                    const text = event.target.value;
                    const next = rows.map((entry) => entry.key === row.key ? { ...entry, value: text } : entry);
                    if (index === rows.length - 1) next.push({ key: generateUUID(6), value: '' });
                    emit(next, { action: 'u', id: row.key, value: text });
                }} className={cname('pr-8', inputClassName)} />
            <Button type="button" variant="text" size="medium" className="absolute right-0 top-0" aria-label={t(index === rows.length - 1 ? 'sharedUi.addItem' : 'sharedUi.removeItem')} onClick={() => index === rows.length - 1
                    ? emit([...rows, { key: generateUUID(6), value: '' }])
                    : emit(rows.filter((entry) => entry.key !== row.key), { action: 'd', id: row.key, value: '' })} color="default" iconOnly>
                {index === rows.length - 1 ? <CirclePlus /> : <CircleMinus />}
            </Button>
        </div>)}
    </div>;
});
