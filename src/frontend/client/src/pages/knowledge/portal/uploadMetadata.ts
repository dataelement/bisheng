import type { SpaceTag } from "~/api/knowledge";
import type { PortalFileCategoryOption } from "./types";

export const DEFAULT_ENCODING_PREFIX = "SGGF";
export const DEFAULT_ENCODING_SERIAL = "00000000000001";

export const BUSINESS_DOMAIN_OPTIONS = [
    { code: "PP", name: "生产" },
    { code: "QM", name: "质量" },
    { code: "PM", name: "设备" },
    { code: "EM", name: "能源" },
    { code: "SA", name: "安全" },
    { code: "EN", name: "环保" },
    { code: "IM", name: "投资" },
    { code: "RD", name: "研发" },
    { code: "MM", name: "采购" },
    { code: "SD", name: "营销" },
    { code: "FI", name: "财务" },
    { code: "HR", name: "人力" },
    { code: "IT", name: "信息" },
    { code: "AD", name: "管理" },
];

export type BusinessDomainOptionItem = {
    code: string;
    name: string;
};

export interface PortalUploadMetadataState {
    businessDomainCode: string;
    selectedTagValues: string[];
}

export interface PortalUploadMetadataPayload {
    file_category_code?: string;
    business_domain_code?: string;
    manual_tag_ids?: number[];
    manual_tag_names?: string[];
}

export interface PortalUploadTagOption {
    label: string;
    value: string;
}

export type EncodingDraft = {
    fileCategoryCode?: string;
    businessDomainCode?: string;
};

export type ParsedFileEncoding = {
    prefix: string;
    fileCategoryCode: string;
    businessDomainCode: string;
    serial: string;
};

export const EMPTY_PORTAL_UPLOAD_METADATA: PortalUploadMetadataState = {
    businessDomainCode: "",
    selectedTagValues: [],
};

export function cleanEncodingText(value?: string | null): string {
    return String(value ?? "").replace(/[\u200B\u200C\u200D\uFEFF]/g, "").trim();
}

export function normalizeEncodingCode(value?: string | null): string {
    return cleanEncodingText(value).toUpperCase();
}

export function normalizeBusinessDomainOptions(
    options?: Array<{ code?: string | null; name?: string | null; label?: string | null }> | null,
): BusinessDomainOptionItem[] {
    const normalizedOptions: BusinessDomainOptionItem[] = [];
    const seen = new Set<string>();
    (options ?? []).forEach((option) => {
        const code = normalizeEncodingCode(option?.code);
        if (!code || seen.has(code)) return;
        const name = cleanEncodingText(option?.name ?? option?.label ?? code) || code;
        normalizedOptions.push({ code, name });
        seen.add(code);
    });
    return normalizedOptions;
}

export function normalizeBusinessDomainCodes(codes?: Array<string | null | undefined> | null): string[] {
    const normalizedCodes: string[] = [];
    const seen = new Set<string>();
    (codes ?? []).forEach((rawCode) => {
        const code = normalizeEncodingCode(rawCode);
        if (!code || seen.has(code)) return;
        normalizedCodes.push(code);
        seen.add(code);
    });
    return normalizedCodes;
}

export function filterBusinessDomainOptionsByCodes(
    options: BusinessDomainOptionItem[],
    boundCodes?: Array<string | null | undefined> | null,
): BusinessDomainOptionItem[] {
    const normalizedBoundCodes = normalizeBusinessDomainCodes(boundCodes);
    if (!normalizedBoundCodes.length) return options;
    const allowedCodes = new Set(normalizedBoundCodes);
    return options.filter((option) => allowedCodes.has(option.code));
}

export function parseFileEncoding(
    encoding?: string | null,
    fallbackPrefix = DEFAULT_ENCODING_PREFIX,
): ParsedFileEncoding {
    const cleaned = String(encoding ?? "").trim();
    const parts = cleaned.split("-").map((part) => part.trim()).filter(Boolean);
    if (parts.length >= 4) {
        return {
            prefix: parts[0] || fallbackPrefix,
            fileCategoryCode: normalizeEncodingCode(parts[1]),
            businessDomainCode: normalizeEncodingCode(parts[2]),
            serial: parts.slice(3).join("-") || DEFAULT_ENCODING_SERIAL,
        };
    }
    const numericSerial = cleaned.replace(/\D/g, "");
    return {
        prefix: fallbackPrefix,
        fileCategoryCode: "",
        businessDomainCode: "",
        serial: numericSerial || DEFAULT_ENCODING_SERIAL,
    };
}

export function composeFileEncoding(
    currentEncoding: string | null | undefined,
    fileCategoryCode: string,
    businessDomainCode: string,
    fallbackPrefix = DEFAULT_ENCODING_PREFIX,
) {
    const parsed = parseFileEncoding(currentEncoding, fallbackPrefix);
    return `${parsed.prefix || fallbackPrefix}-${fileCategoryCode}-${businessDomainCode}-${parsed.serial || DEFAULT_ENCODING_SERIAL}`;
}

export function fileEncodingCategoryLabel(code: string, options: PortalFileCategoryOption[]): string {
    const normalizedCode = normalizeEncodingCode(code);
    if (!normalizedCode) return "未识别";
    const option = options.find((item) => normalizeEncodingCode(item.code) === normalizedCode);
    const label = option ? cleanEncodingText(option.label) : "";
    return label ? `${normalizedCode} / ${label}` : `${normalizedCode} / 未配置类型`;
}

export function fileEncodingBusinessDomainLabel(
    code: string,
    options: BusinessDomainOptionItem[] = BUSINESS_DOMAIN_OPTIONS,
): string {
    if (!code) return "未识别";
    const normalizedCode = normalizeEncodingCode(code);
    const option = options.find((item) => item.code === normalizedCode)
        ?? BUSINESS_DOMAIN_OPTIONS.find((item) => item.code === normalizedCode);
    return option ? `${code} / ${option.name}` : `${code} / 未配置业务域`;
}

export function parseUploadTagValues(values: string[]) {
    const manualTagIds: number[] = [];
    const manualTagNames: string[] = [];
    const seenIds = new Set<number>();
    const seenNames = new Set<string>();

    values.forEach((value) => {
        if (value.startsWith("id:")) {
            const id = Number(value.slice(3));
            if (Number.isInteger(id) && id > 0 && !seenIds.has(id)) {
                seenIds.add(id);
                manualTagIds.push(id);
            }
            return;
        }
        if (value.startsWith("name:")) {
            const name = value.slice(5).trim();
            if (name && !seenNames.has(name)) {
                seenNames.add(name);
                manualTagNames.push(name);
            }
        }
    });

    return { manualTagIds, manualTagNames };
}

export function buildPortalUploadMetadataPayload(
    metadata: PortalUploadMetadataState,
    fileCategoryCode?: string,
): PortalUploadMetadataPayload {
    const payload: PortalUploadMetadataPayload = {};
    if (fileCategoryCode) {
        payload.file_category_code = fileCategoryCode;
    }
    if (metadata.businessDomainCode) {
        payload.business_domain_code = metadata.businessDomainCode;
    }
    const parsedTags = parseUploadTagValues(metadata.selectedTagValues);
    if (parsedTags.manualTagIds.length) {
        payload.manual_tag_ids = parsedTags.manualTagIds;
    }
    if (parsedTags.manualTagNames.length) {
        payload.manual_tag_names = parsedTags.manualTagNames;
    }
    return payload;
}

export function buildUploadTagOptions(
    existingTags: SpaceTag[],
    commonTagNames: string[],
): PortalUploadTagOption[] {
    const options: PortalUploadTagOption[] = [];
    const seenNames = new Set<string>();

    existingTags.forEach((tag) => {
        const name = String(tag.name ?? "").trim();
        const id = Number(tag.id);
        if (!name || !Number.isInteger(id) || id <= 0 || seenNames.has(name)) return;
        seenNames.add(name);
        const value = tag.business_type === "tag_library" ? `name:${name}` : `id:${id}`;
        options.push({ label: name, value });
    });

    commonTagNames.forEach((tagName) => {
        const name = String(tagName ?? "").trim();
        if (!name || seenNames.has(name)) return;
        seenNames.add(name);
        options.push({ label: name, value: `name:${name}` });
    });

    return options;
}

/** Deduplicate tag names from bound tag libraries (by display name). */
export function extractUniqueLibraryTagNames(
    items: Array<{ name?: string | null }>,
): string[] {
    const seenNames = new Set<string>();
    const names: string[] = [];
    for (const item of items) {
        const name = String(item.name ?? "").trim();
        if (!name || seenNames.has(name)) continue;
        seenNames.add(name);
        names.push(name);
    }
    return names;
}
