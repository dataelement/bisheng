import type { UploadFileKind } from "@/util/fileAcceptUtils";
export const enum FormType {
    Text = "text",
    Select = "select",
    File = "file",
}

export const names = {
    [FormType.Text]: "text_input",
    [FormType.Select]: "category",
    [FormType.File]: "file",
}


export const enum FileProcessingStrategy {
    TempKnowledge = "ingest_to_temp_kb",
    ParseContent = "extract_text",
    OriginalFile = "keep_raw",
}


// fixed atomic-mode array. The 3 named options map to fixed arrays.
export const enum FormOption {
    ParseOnly = "parse_only",
    ParseIngest = "parse_ingest",
    NoParse = "no_parse",
}
export const optionToModes = (opt: FormOption): FileProcessingStrategy[] =>
    opt === FormOption.NoParse
        ? [FileProcessingStrategy.OriginalFile]
        : opt === FormOption.ParseIngest
            ? [FileProcessingStrategy.ParseContent, FileProcessingStrategy.TempKnowledge]
            : [FileProcessingStrategy.ParseContent];
// Normalize any stored value (array / legacy string / superseded multi-array) into one option.
export const modesToOption = (value: unknown): FormOption => {
    const arr = Array.isArray(value) ? value : (value ? [value] : []);
    if (arr.includes(FileProcessingStrategy.TempKnowledge)) return FormOption.ParseIngest;
    if (arr.includes(FileProcessingStrategy.ParseContent)) return FormOption.ParseOnly;
    if (arr.includes(FileProcessingStrategy.OriginalFile)) return FormOption.NoParse;
    return FormOption.ParseOnly;
};
export const optIngests = (opt: Partial<SerializedInputField> | undefined): boolean =>
    modesToOption(opt?.file_parse_mode) === FormOption.ParseIngest;


import type { WorkflowNodeParam } from "@/types/flow";
export interface InputOption { id: string; text: string; type: string }
export interface InputFormDraft {
    formType: FormType; displayName: string; variableName: string;
    filecontent: string; filepath: string; fileType: string | UploadFileKind[]; fileContentSize: number;
    imageFile: string; isMultiple: boolean; isRequired: boolean; allowMultiple: boolean;
    options: InputOption[]; processingOption?: FormOption;
}
export interface SerializedInputField {
    type: FormType; value: string; key: string; required: boolean; multiple: boolean;
    file_content: string; file_type: string | UploadFileKind[]; file_path: string; file_content_size: number;
    image_file: string; file_parse_mode?: unknown; options?: InputOption[];
}
export interface InputFormEditorProps {
    nodeId: string; nodeData: WorkflowNodeParam; initialData?: SerializedInputField | null;
    onSubmit: (draft: InputFormDraft) => void; onCancel: () => void;
    existingOptions?: SerializedInputField[];
}
