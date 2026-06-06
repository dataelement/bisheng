import type { SpaceTag } from "~/api/knowledge";

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

export const EMPTY_PORTAL_UPLOAD_METADATA: PortalUploadMetadataState = {
    businessDomainCode: "",
    selectedTagValues: [],
};

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
        options.push({ label: name, value: `id:${id}` });
    });

    commonTagNames.forEach((tagName) => {
        const name = String(tagName ?? "").trim();
        if (!name || seenNames.has(name)) return;
        seenNames.add(name);
        options.push({ label: name, value: `name:${name}` });
    });

    return options;
}
