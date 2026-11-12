import { stripIdentityWhitespace } from '@bisheng/identity';
import { Button, Tooltip } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { useTranslation } from 'react-i18next';

interface IdentityRuleHintProps {
    field: 'account' | 'nickname';
    expanded: boolean;
    controls: string;
    onToggle: () => void;
}

export function IdentityRuleHint({ field, expanded, controls, onToggle }: IdentityRuleHintProps) {
    const { t } = useTranslation();
    return <Tooltip content={t(`accountIdentity.${field}Rules`)}>
        <Button type="button" variant="text" color="default" size="small" iconOnly
            aria-label={t(`accountIdentity.${field}RulesLabel`)}
            aria-expanded={expanded} aria-controls={controls} onClick={onToggle}>
            <Outlined.Question aria-hidden />
        </Button>
    </Tooltip>;
}

export function updateIdentityInput(input: HTMLInputElement, onValue: (value: string) => void, composing = false) {
    const raw = input.value;
    const value = composing ? raw : stripIdentityWhitespace(raw);
    const start = stripIdentityWhitespace(raw.slice(0, input.selectionStart ?? raw.length)).length;
    const end = stripIdentityWhitespace(raw.slice(0, input.selectionEnd ?? raw.length)).length;
    if (value !== raw) input.value = value;
    onValue(value);
    if (value !== raw) requestAnimationFrame(() => {
        if (input.isConnected && document.activeElement === input) input.setSelectionRange(start, end);
    });
}
