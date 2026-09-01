export const formatExcelHeaderValue = (value: unknown): string => {
    return value === undefined || value === null ? "" : String(value);
};
