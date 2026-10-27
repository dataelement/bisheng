// Types
export interface MetadataItem {
    id: string;
    name: string;
    type: 'String' | 'Number' | 'Time';
    value?: string;
    description?: string;
    updated?: number;
    updated_at?: string | number;
}

export interface FileInfo {
    id?: string;
    file_name?: string;
    create_time?: string;
    update_time?: string;
    creat_user?: string;
    update_user?: string;
    file_size?: number;
    split_rule?: string;
    title?: string;
    user_metadata?: Record<string, unknown>;
}

export interface MetadataDialogProps {
    open: boolean;
    file: FileInfo | null;
}

export interface SideDialogProps {
    type: 'search' | 'create' | null;
    open: boolean;
}

export interface NewMetadata {
    name: string;
    type: 'String' | 'Number' | 'Time';
}

