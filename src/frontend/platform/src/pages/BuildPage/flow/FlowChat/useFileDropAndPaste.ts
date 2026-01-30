import { useState, useRef, useEffect, useCallback } from 'react';

export const useFileDropAndPaste = ({ enabled, onFilesReceived }) => {
    const [isDragging, setIsDragging] = useState(false);
    const dragCounter = useRef(0);

    // 1.  (full drag)
    useEffect(() => {
        if (!enabled) return;

        const handleDragEnter = (e) => {
            e.preventDefault();
            e.stopPropagation();
            dragCounter.current += 1;
            // vailte file type
            if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
                setIsDragging(true);
            }
        };

        const handleDragLeave = (e) => {
            e.preventDefault();
            e.stopPropagation();
            dragCounter.current -= 1;
            if (dragCounter.current === 0) {
                setIsDragging(false);
            }
        };

        const handleDragOver = (e) => {
            e.preventDefault();
            e.stopPropagation();
        };

        const handleDrop = (e) => {
            e.preventDefault();
            e.stopPropagation();
            setIsDragging(false);
            dragCounter.current = 0;

            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                onFilesReceived(e.dataTransfer.files);
                e.dataTransfer.clearData();
            }
        };

        window.addEventListener('dragenter', handleDragEnter);
        window.addEventListener('dragleave', handleDragLeave);
        window.addEventListener('dragover', handleDragOver);
        window.addEventListener('drop', handleDrop);

        return () => {
            window.removeEventListener('dragenter', handleDragEnter);
            window.removeEventListener('dragleave', handleDragLeave);
            window.removeEventListener('dragover', handleDragOver);
            window.removeEventListener('drop', handleDrop);
        };
    }, [enabled, onFilesReceived]);

    // 2. pasete
    const handlePaste = useCallback((e) => {
        if (!enabled) return;

        const items = e.clipboardData?.items;
        const files = [];
        if (items) {
            for (let i = 0; i < items.length; i++) {
                if (items[i].kind === 'file') {
                    const file = items[i].getAsFile();
                    if (file) files.push(file);
                }
            }
        }

        if (files.length > 0) {
            e.preventDefault(); // Prevent default paste behavior (to avoid pasting file names into the input box)
            onFilesReceived(files);
        }
    }, [enabled, onFilesReceived]);

    return {
        isDragging,
        handlePaste
    };
};