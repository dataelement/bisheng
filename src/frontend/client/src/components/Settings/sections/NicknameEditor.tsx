import { useId, useRef, useState, type ChangeEvent, type FormEvent, type KeyboardEvent } from 'react';
import { Button, Input } from '@bisheng/ui';
import { characterCount, stripIdentityWhitespace, validateNicknameChange } from '@bisheng/identity';
import { isApiError } from '@bisheng/api-client';
import { updateNicknameApi, type NicknameProfile } from '~/api/user';
import { useLocalize } from '~/hooks';

interface NicknameEditorProps {
    nickname: string;
    autoFocus?: boolean;
    onCancel: () => void;
    onSaved: (profile: NicknameProfile) => void;
}

export function NicknameEditor({ nickname, autoFocus = true, onCancel, onSaved }: NicknameEditorProps) {
    const localize = useLocalize();
    const errorId = useId();
    const [value, setValue] = useState(nickname);
    const [saving, setSaving] = useState(false);
    const [serverError, setServerError] = useState<string>();
    const pending = useRef(false);
    const errorCode = validateNicknameChange(value, nickname);
    const error = errorCode ? localize(`accountIdentity.errors.${errorCode}`) : serverError;

    const handleInputValue = (input: HTMLInputElement, composing = false) => {
        const raw = input.value;
        const next = composing ? raw : stripIdentityWhitespace(raw);
        const start = stripIdentityWhitespace(raw.slice(0, input.selectionStart ?? raw.length)).length;
        const end = stripIdentityWhitespace(raw.slice(0, input.selectionEnd ?? raw.length)).length;
        if (next !== raw) input.value = next;
        setValue(next);
        if (next !== value) setServerError(undefined);
        if (next !== raw) requestAnimationFrame(() => {
            if (input.isConnected && document.activeElement === input) input.setSelectionRange(start, end);
        });
    };
    const handleChange = (event: ChangeEvent<HTMLInputElement>) =>
        handleInputValue(event.currentTarget, (event.nativeEvent as InputEvent).isComposing);

    const handleInputKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
        if (event.key !== 'Enter' || event.nativeEvent.isComposing || event.keyCode === 229) return;
        event.preventDefault();
        if (!event.repeat) event.currentTarget.form?.requestSubmit();
    };

    const handleSubmit = async (event: FormEvent) => {
        event.preventDefault();
        if (pending.current || value === nickname || errorCode) return;
        pending.current = true;
        setSaving(true);
        setServerError(undefined);
        let saved: NicknameProfile;
        try {
            saved = await updateNicknameApi(value);
        } catch (cause) {
            setServerError(isApiError(cause) ? cause.message : localize('accountIdentity.saveFailed'));
            return;
        } finally {
            pending.current = false;
            setSaving(false);
        }
        onSaved(saved);
    };

    return <form onSubmit={handleSubmit}
        onKeyDown={event => {
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                if (!pending.current) onCancel();
            }
        }} noValidate>
        <div className="flex flex-wrap items-center gap-2">
            <Input size="medium" className="min-w-0 max-w-[22rem] flex-1 basis-48" value={value} autoFocus={autoFocus} disabled={saving}
                enterKeyHint="done" onChange={handleChange} onKeyDown={handleInputKeyDown}
                onCompositionEnd={event => handleInputValue(event.currentTarget)}
                status={error ? 'error' : 'default'} aria-invalid={Boolean(error)}
                aria-label={localize('accountIdentity.nickname')} aria-describedby={error ? errorId : undefined}
                suffix={<span className="text-caption text-text-3">{characterCount(value)}/32</span>} />
            <div className="ms-auto flex max-w-full flex-wrap justify-end gap-2">
                <Button type="button" variant="outlined" color="default" disabled={saving} onClick={onCancel}>
                    {localize('com_ui_cancel')}
                </Button>
                <Button type="submit" disabled={saving || value === nickname || Boolean(errorCode)} loading={saving}>
                    {localize('com_ui_save')}
                </Button>
            </div>
        </div>
        <p id={errorId} className={error ? 'mt-2 text-caption text-danger' : undefined} aria-live="polite">
            {error}
        </p>
    </form>;
}
