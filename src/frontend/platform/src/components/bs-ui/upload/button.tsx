import { useState, useRef, useCallback } from 'react';
import axios, { AxiosProgressEvent, CancelTokenSource } from 'axios';
import { Button } from "../button";
// TODO 待测试组件

interface UploadButtonProps {
    uploadUrl: string;
    allowedFileTypes?: string[];
    maxFileSize?: number; // 单位：MB
    multiple?: boolean;
    formParams?: Record<string, any>;
    className?: string;
    children?: React.ReactNode;
    onSuccess?: (response: any) => void;
    onError?: (error: Error) => void;
    onProgress?: (percentage: number) => void;
    onBeforeUpload?: (files: File[]) => boolean;
}

export default function UploadButton({
    uploadUrl,
    allowedFileTypes = [],
    maxFileSize = 10, // 默认10MB
    multiple = false,
    formParams = {},
    className,
    children = 'Upload',
    onSuccess,
    onError,
    onProgress,
    onBeforeUpload
}: UploadButtonProps) {
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [isUploading, setIsUploading] = useState(false);
    const [previews, setPreviews] = useState<string[]>([]);
    const [dragActive, setDragActive] = useState(false);
    const cancelToken = useRef<CancelTokenSource>();

    // 生成预览图
    const generatePreviews = useCallback((files: File[]) => {
        const imageFiles = files.filter(file => file.type.startsWith('image/'));
        const previewPromises = imageFiles.map(file =>
            new Promise<string>((resolve) => {
                const reader = new FileReader();
                reader.onload = (e) => resolve(e.target?.result as string);
                reader.readAsDataURL(file);
            })
        );

        Promise.all(previewPromises).then(urls => {
            setPreviews(prev => [...prev, ...urls]);
        });
    }, []);

    // 处理文件校验
    const validateFiles = (files: File[]) => {
        // 文件类型校验
        if (allowedFileTypes.length > 0) {
            const isValid = files.every(file =>
                allowedFileTypes.includes(file.type)
            );
            if (!isValid) {
                throw new Error(`只支持以下文件类型: ${allowedFileTypes.join(', ')}`);
            }
        }

        // 文件大小校验
        if (maxFileSize > 0) {
            const sizeValid = files.every(file =>
                file.size <= maxFileSize * 1024 * 1024
            );
            if (!sizeValid) {
                throw new Error(`文件大小不能超过 ${maxFileSize}MB`);
            }
        }
    };

    const handleUpload = async (files: File[]) => {
        try {
            // 校验文件
            validateFiles(files);

            // 上传前回调
            if (onBeforeUpload && !onBeforeUpload(files)) return;

            setIsUploading(true);
            const formData = new FormData();

            // 添加表单参数
            Object.entries(formParams).forEach(([key, value]) => {
                formData.append(key, value);
            });

            // 添加文件
            files.forEach(file => {
                formData.append('files', file);
            });

            // 生成预览
            generatePreviews(files);

            // 创建取消令牌
            cancelToken.current = axios.CancelToken.source();

            const response = await axios.post(uploadUrl, formData, {
                onUploadProgress: (progressEvent: AxiosProgressEvent) => {
                    if (progressEvent.total) {
                        const percent = Math.round(
                            (progressEvent.loaded * 100) / progressEvent.total
                        );
                        onProgress?.(percent);
                    }
                },
                cancelToken: cancelToken.current.token
            });

            onSuccess?.(response.data);
        } catch (err) {
            if (!axios.isCancel(err)) {
                onError?.(err as Error);
            }
        } finally {
            setIsUploading(false);
        }
    };

    // 拖拽处理
    const handleDrag = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.type === 'dragover') {
            setDragActive(true);
        } else if (e.type === 'dragleave') {
            setDragActive(false);
        }
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setDragActive(false);

        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            const files = Array.from(e.dataTransfer.files);
            handleUpload(files);
        }
    };

    // 文件选择处理
    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = Array.from(e.target.files || []);
        if (files.length > 0) {
            handleUpload(files);
        }
    };

    return (
        <div className={className}>
            {/* 拖拽区域 */}
            <div
                className={`drag-area ${dragActive ? 'drag-active' : ''}`}
                onDragOver={handleDrag}
                onDragLeave={handleDrag}
                onDrop={handleDrop}
                style={{
                    border: '2px dashed #ccc',
                    padding: '20px',
                    marginBottom: '10px',
                    backgroundColor: dragActive ? '#f0f8ff' : 'transparent'
                }}
            >
                拖拽文件到此区域或点击下方按钮上传

                {/* 预览区域 */}
                {previews.length > 0 && (
                    <div style={{
                        display: 'flex',
                        gap: '10px',
                        flexWrap: 'wrap',
                        marginTop: '10px'
                    }}>
                        {previews.map((src, index) => (
                            <img
                                key={index}
                                src={src}
                                alt={`预览-${index}`}
                                style={{
                                    width: '100px',
                                    height: '100px',
                                    objectFit: 'cover',
                                    borderRadius: '4px'
                                }}
                            />
                        ))}
                    </div>
                )}
            </div>

            <Button
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading}
                style={{ width: '100%' }}
            >
                {isUploading ? '上传中...' : children}
            </Button>

            <input
                type="file"
                ref={fileInputRef}
                style={{ display: 'none' }}
                multiple={multiple}
                accept={allowedFileTypes.join(',')}
                onChange={handleFileChange}
            />
        </div>
    );
}