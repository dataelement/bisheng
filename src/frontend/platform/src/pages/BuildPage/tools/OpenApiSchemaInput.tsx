import { Button, Dropdown, DropdownChevron, DropdownItem, Input, Textarea } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Popover, PopoverClose, PopoverContent, PopoverTrigger } from '@/components/bs-ui/popover';
import type { OpenApiSchemaSource } from '@/controllers/API/tools';
import { showApiError } from '@/controllers/request';
import { Example } from './toolSchemaExamples';

interface OpenApiSchemaInputProps {
    value: string;
    onChange: (value: string) => void;
    onParse: (source: OpenApiSchemaSource) => Promise<void>;
    disabled?: boolean;
    id?: string;
    examples?: boolean;
    parseOnBlur?: boolean;
}

export function OpenApiSchemaInput({ value, onChange, onParse, disabled = false, id = 'schemaContent', examples = true, parseOnBlur = true }: OpenApiSchemaInputProps) {
    const { t } = useTranslation();
    const [url, setUrl] = useState('');
    const parsedContent = useRef<string | null>(null);
    const [busy, setBusy] = useState(false);
    const unavailable = disabled || busy;
    const handleParse = async (source: OpenApiSchemaSource) => {
        if (unavailable) return;
        setBusy(true);
        try {
            await onParse(source);
            if ('file_content' in source) parsedContent.current = source.file_content;
            if ('download_url' in source) setUrl('');
        } catch (error) {
            showApiError(error);
        } finally {
            setBusy(false);
        }
    };
    return <div>
        <div className="flex items-center justify-between">
            <label htmlFor={id}>OpenAPI Schema</label>
            <div className="flex gap-2">
                <Popover>
                    <PopoverTrigger asChild>
                        <Button type="button" variant="outlined" color="default" disabled={unavailable}><Outlined.Plus /> {t('tools.importFromUrl')}</Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-80" align="end">
                        <div className="flex items-center gap-4">
                            <Input id={`${id}-url`} name="schemaUrl" aria-label={String(t('tools.importFromUrl'))} placeholder="https://" value={url} onChange={(event) => setUrl(event.target.value)} />
                            <PopoverClose asChild>
                                <Button type="button" size="small" disabled={unavailable || !url.trim()} onClick={() => handleParse({ download_url: url })}>{t('skills.import')}</Button>
                            </PopoverClose>
                        </div>
                    </PopoverContent>
                </Popover>
                {examples && <Dropdown align="end" menu={<>
                    <DropdownItem onSelect={() => handleParse({ file_content: Example.json })}>{t('tools.weatherJson')}</DropdownItem>
                    <DropdownItem onSelect={() => handleParse({ file_content: Example.yaml })}>{t('tools.petShopYaml')}</DropdownItem>
                </>}>
                    <Button type="button" variant="outlined" color="default" disabled={unavailable}>{t('tools.examples')}<DropdownChevron /></Button>
                </Dropdown>}
            </div>
        </div>
        <Textarea id={id} name="schemaContent" placeholder={String(t('tools.enterOpenAPISchema'))} value={value} disabled={unavailable} onChange={(event) => onChange(event.target.value)} onBlur={() => {
            if (parseOnBlur && value.trim() && value !== parsedContent.current) void handleParse({ file_content: value });
        }} textareaClassName="mt-2 min-h-52" />
        {!parseOnBlur && <Button type="button" disabled={unavailable || !value.trim()} onClick={() => handleParse({ file_content: value })}>{t('chatConfig.webSearch.parse')}</Button>}
    </div>;
}
