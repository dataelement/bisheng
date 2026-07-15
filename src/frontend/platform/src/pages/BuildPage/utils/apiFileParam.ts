export type FileParamValue = {
    name: string;
    content_type: string;
    encoding: 'base64';
    content: string;
};

export type OpenApiToolParam = {
    content_type?: string;
    schema?: {
        format?: string;
    };
};

export const isBinaryOpenApiParam = (param: OpenApiToolParam) => {
    return param?.content_type === 'multipart/form-data' && param?.schema?.format === 'binary';
};

export const readFileParam = (file: File): Promise<FileParamValue> => {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
            const result = typeof reader.result === 'string' ? reader.result : '';
            const content = result.includes(',') ? result.split(',', 2)[1] : result;
            resolve({
                name: file.name,
                content_type: file.type || 'application/octet-stream',
                encoding: 'base64',
                content,
            });
        };
        reader.onerror = () => reject(reader.error || new Error('failed to read file'));
        reader.readAsDataURL(file);
    });
};
