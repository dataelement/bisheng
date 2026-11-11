import { useRef, useState, type ChangeEvent, type FormEvent } from 'react';
import { Button, Input } from '@bisheng/ui';
import { characterCount, stripIdentityWhitespace, validateNicknameChange } from '@bisheng/identity';
import { isApiError } from '@bisheng/api-client';
import { updateNicknameApi, type NicknameProfile } from '~/api/user';
import { useLocalize } from '~/hooks';

interface NicknameEditorProps {
    nickname: string;
    onCancel: () => void;
    onSaved: (profile: NicknameProfile) => void;
}

export function NicknameEditor({ nickname, onCancel, onSaved }: NicknameEditorProps) {
    const localize = useLocalize();
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

    return <form className="grid gap-2 border-b border-border pb-5" onSubmit={handleSubmit}
        onKeyDown={event => {
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                if (!pending.current) onCancel();
            }
        }} noValidate>
        <label htmlFor="profile-nickname" className="text-body text-text-1">{localize('accountIdentity.nickname')}</label>
        <Input id="profile-nickname" size="medium" value={value} autoFocus disabled={saving}
            onChange={handleChange} onCompositionEnd={event => handleInputValue(event.currentTarget)}
            status={error ? 'error' : 'default'} aria-invalid={Boolean(error)}
            aria-describedby="profile-nickname-rule profile-nickname-effect"
            suffix={<span className="text-caption text-text-3">{characterCount(value)}/32</span>} />
        <p id="profile-nickname-rule" className={`text-caption ${error ? 'text-danger' : 'text-text-3'}`} aria-live="polite">
            {error || localize('accountIdentity.nicknameRules')}
        </p>
        <p id="profile-nickname-effect" className="text-caption text-text-3">{localize('accountIdentity.nicknameEffectSelf')}</p>
        <div className="mt-2 flex justify-end gap-2">
            <Button type="button" variant="outlined" color="default" disabled={saving} onClick={onCancel}>
                {localize('com_ui_cancel')}
            </Button>
            <Button type="submit" disabled={saving || value === nickname || Boolean(errorCode)} loading={saving}>
                {localize('accountIdentity.saveNickname')}
            </Button>
        </div>
    </form>;
}
