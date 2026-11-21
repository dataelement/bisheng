import { Button, Dropdown, DropdownChevron, DropdownItem, toast } from '@bisheng/ui';

import { locationContext } from "@/contexts/locationContext";
import { Outlined } from "bisheng-icons";
import { useContext, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useDropzone } from "react-dropzone";
import { useTranslation } from "react-i18next";

const XIN_CHUANG_FORMATS = ['.WPS', '.ET', '.DPS'];
const MEDIA_FORMATS = ['.MP3', '.WAV', '.M4A', '.AAC', '.FLAC', '.OGG', '.MP4', '.MOV', '.AVI', '.MKV', '.WEBM'];

export function getKnowledgeUploadFormats(
    enableEtl4lm: boolean,
    mediaEnabled = false
): string[] {
    const enabledMediaFormats = mediaEnabled ? MEDIA_FORMATS : [];
    return enableEtl4lm
        ? ['.PDF', '.OFD', '.TXT', '.DOCX', '.PPT', '.PPTX', '.MD', '.HTML', '.XLS', '.XLSX', '.CSV', '.DOC', '.PNG', '.JPG', '.JPEG', '.BMP', ...XIN_CHUANG_FORMATS, ...enabledMediaFormats]
        : ['.PDF', '.OFD', '.TXT', '.DOCX', '.DOC', '.PPT', '.PPTX', '.MD', '.HTML', '.XLS', '.XLSX', '.CSV', ...XIN_CHUANG_FORMATS, ...enabledMediaFormats];
}

export function getKnowledgeUploadAccept(
    supportedFormats: string[],
    mediaEnabled = false
): Record<string, string[]> {
    return {
        'application/*': supportedFormats,
        'text/*': supportedFormats,
        'image/*': supportedFormats,
        ...(mediaEnabled
            ? {
                'audio/*': supportedFormats,
                'video/*': supportedFormats,
            }
            : {}),
    };
}

interface DropZoneProps {
    onDrop: (files: File[]) => void;
    onFolderDrop?: (files: File[]) => void;
    compact?: boolean;
}

export default function DropZone({ onDrop, onFolderDrop, compact = false }: DropZoneProps) {
    const { t } = useTranslation()
    const { appConfig } = useContext(locationContext)
    const mediaEnabled = !!appConfig.enableMediaUpload;
    const folderInput = useRef<HTMLInputElement>(null);
    const pickerButton = useRef<HTMLButtonElement>(null);
    const [pickerMenu, setPickerMenu] = useState({ open: false, x: 0, y: 0 });
    const descriptionId = useId();
    const hasPickerMenu = !!onFolderDrop;

    const supportedFormats = getKnowledgeUploadFormats(appConfig.enableEtl4lm, mediaEnabled);
    const allowedExts = new Set(
        supportedFormats.map(ext => ext.toLowerCase().replace('.', ''))
    );
    const { getRootProps, getInputProps, open } = useDropzone({
        accept: getKnowledgeUploadAccept(supportedFormats, mediaEnabled),
        noClick: hasPickerMenu,
        noKeyboard: hasPickerMenu,
        useFsAccessApi: false,
        onDrop: (acceptedFiles, disAcceptedFiles) => {
            // Filter files that don't match the allowed formats
            const validFiles = acceptedFiles.filter(file => {
                // Get file extension (if no extension, consider invalid)
                const ext = file.name.split('.').pop()?.toLowerCase();
                return ext ? allowedExts.has(ext) : false;
            });

            if (disAcceptedFiles.length > 0) {
                // @ts-ignore
                const uniqueExtensions = [...new Set(
                    disAcceptedFiles
                        .map(f => f.file.name.split('.').pop()?.toLowerCase())
                        .filter(Boolean)
                )];
                toast.show({ type: 'error', message: [String(t('prompt') ?? ''), String(t('unsupportedFileType', { extensions: uniqueExtensions.join(', ') }) ?? '')].filter(Boolean).join('\n') });
            }

            // Only pass valid files to parent component
            if (validFiles.length > 0) {
                onDrop(validFiles);
            }
        }
    });

    const mediaMaxSize = appConfig.uploadMediaMaxSize ?? 1024;
    const formatKey = appConfig.enableEtl4lm
        ? (mediaEnabled ? 'supportedFormatsWithImages' : 'supportedFormatsWithImagesWithoutMedia')
        : (mediaEnabled ? 'supportedFormatsWithoutImages' : 'supportedFormatsWithoutImagesWithoutMedia');
    const formatText = t(formatKey, { maxSize: appConfig.uploadFileMaxSize ?? 50, mediaMaxSize });

    if (onFolderDrop) {
        const pickerLabel = t('f118.upload_picker_trigger', { ns: 'knowledge' });
        const openPickerAtButton = (button: HTMLButtonElement) => {
            const { left, bottom } = button.getBoundingClientRect();
            setPickerMenu({ open: true, x: left, y: bottom });
        };

        return (
            <div {...getRootProps()}>
                <input {...getInputProps()} />
                <input
                    type="file"
                    multiple
                    className="hidden"
                    aria-label={t('f118.upload_folder', { ns: 'knowledge' })}
                    ref={folderInput}
                    {...{ webkitdirectory: "", directory: "" }}
                    onChange={(event) => {
                        const input = event.currentTarget;
                        onFolderDrop(Array.from(input.files ?? []));
                        input.value = "";
                    }}
                />
                <Button
                    ref={pickerButton}
                    type="button"
                    color="default"
                    variant="text"
                    aria-label={pickerLabel}
                    aria-describedby={descriptionId}
                    aria-haspopup="menu"
                    aria-expanded={pickerMenu.open}
                    data-menu-open={pickerMenu.open ? '' : undefined}
                    onClick={(event) => {
                        if (event.detail > 0) {
                            setPickerMenu({ open: true, x: event.clientX, y: event.clientY });
                        } else {
                            openPickerAtButton(event.currentTarget);
                        }
                    }}
                    onKeyDown={(event) => {
                        if (event.key === 'ArrowDown') {
                            event.preventDefault();
                            openPickerAtButton(event.currentTarget);
                        }
                    }}
                    className="group/dropdown min-h-48 w-full flex-col gap-3 whitespace-normal border border-dashed border-border-base py-5 hover:border-blue-500 data-[menu-open]:border-blue-500"
                >
                    <Outlined.Upload aria-hidden />
                    <span className="inline-flex items-center gap-2 text-body text-text-1">
                        {pickerLabel}
                        <DropdownChevron />
                    </span>
                    <span id={descriptionId} className="text-body leading-none text-text-3">
                        {formatText}
                    </span>
                </Button>
                {/* The point anchor uses viewport coordinates, including inside a scroll container. */}
                {createPortal(
                    <Dropdown
                        open={pickerMenu.open}
                        onOpenChange={(open) => setPickerMenu((menu) => ({ ...menu, open }))}
                        onCloseAutoFocus={(event) => {
                            event.preventDefault();
                            pickerButton.current?.focus({ preventScroll: true });
                        }}
                        menu={
                            <>
                                <DropdownItem icon={<Outlined.File aria-hidden />} onSelect={open}>
                                    {t('f118.choose_files', { ns: 'knowledge' })}
                                </DropdownItem>
                                <DropdownItem icon={<Outlined.FolderClose aria-hidden />} onSelect={() => folderInput.current?.click()}>
                                    {t('f118.choose_folder', { ns: 'knowledge' })}
                                </DropdownItem>
                            </>
                        }
                    >
                        <button
                            type="button"
                            aria-hidden="true"
                            aria-label={pickerLabel}
                            tabIndex={-1}
                            className="pointer-events-none fixed size-0 opacity-0"
                            style={{ left: pickerMenu.x, top: pickerMenu.y }}
                        />
                    </Dropdown>,
                    document.body,
                )}
            </div>
        );
    }

    return (
      <>
        <div {...getRootProps()} className={compact
            ? "group flex min-h-36 cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border-deep bg-fill-1 px-6 py-5 text-center transition-colors hover:border-blue-500 hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40"
            : "group h-48 border border-dashed rounded-md flex flex-col justify-center items-center cursor-pointer gap-3 hover:border-primary"}>
            <input {...getInputProps()} />
            <Outlined.Upload className={compact ? "size-8 text-blue-500" : "group-hover:text-primary size-5"} aria-hidden="true" />
            <p className="text-body text-text-1">{t('code.clickOrDragHere')}</p>
            <p className={compact ? "text-caption text-text-3" : "px-4 text-center text-body leading-none text-text-3"}>
                {compact ? t(mediaEnabled ? 'f118.upload_limits_media' : 'f118.upload_limits', {
                    ns: 'knowledge', maxSize: appConfig.uploadFileMaxSize ?? 50, mediaMaxSize,
                }) : formatText}
            </p>
        </div>
        {compact && (
            <details className="text-caption text-text-3">
                <summary className="cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40">{t('f118.upload_formats', { ns: 'knowledge' })}</summary>
                <p className="mt-2 max-w-4xl break-words leading-5">{formatText}</p>
            </details>
        )}
      </>
    );
};
