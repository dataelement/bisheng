const truthyValues = new Set(["true", "1", "yes", "on"]);
const falsyValues = new Set(["false", "0", "no", "off", ""]);

const toBoolean = (value: unknown, fallback: boolean) => {
    if (typeof value === "boolean") return value;
    if (typeof value === "number") return value !== 0;
    if (typeof value === "string") {
        const normalized = value.trim().toLowerCase();
        if (truthyValues.has(normalized)) return true;
        if (falsyValues.has(normalized)) return false;
    }
    if (value == null) return fallback;
    return Boolean(value);
};

export const getDialogInputUploadSettings = (inputSchema: any) => {
    if (inputSchema?.tab !== "dialog_input") {
        return {
            showUpload: false,
            fileAccept: undefined,
        };
    }

    const value = inputSchema.value || [];
    const schemaItem = value.find((el) => el?.key === "dialog_file_accept");
    const switchItem = value.find((el) => el?.key === "user_input_file");

    return {
        fileAccept: schemaItem?.value,
        showUpload: switchItem ? toBoolean(switchItem.value, true) : true,
    };
};
