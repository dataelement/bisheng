import type { CascaderOption, CascaderPath, SelectOption } from '@bisheng/ui';

/** Provider → models tree as `useModel()` builds it. */
export interface ModelProviderNode {
    value: string | number;
    label: string;
    children?: { value: string | number; label: string }[];
}

/**
 * Keep providers as navigation-only parents and models as selectable leaves.
 * Values are stringified so numeric ids from forms and string ids from APIs
 * resolve to the same controlled Cascader path.
 */
export function toModelCascaderOptions(tree: ModelProviderNode[] | undefined): CascaderOption[] {
    return (tree ?? []).flatMap((provider) => {
        if (provider.value == null || provider.value === '') return [];

        const children = (provider.children ?? [])
            .filter((model) => model.value != null && model.value !== '')
            .map((model) => ({ value: String(model.value), label: model.label }));

        return children.length > 0
            ? [{ value: String(provider.value), label: provider.label, children }]
            : [];
    });
}

/** Resolve a stored leaf id to the full provider/model path required by Cascader. */
export function toModelCascaderValue(
    value: unknown,
    tree: ModelProviderNode[] | undefined,
): CascaderPath | null {
    if (value == null || value === '') return null;

    const modelId = String(value);
    for (const provider of tree ?? []) {
        if (provider.value == null || provider.value === '') continue;
        const model = provider.children?.find((item) => String(item.value) === modelId);
        if (model?.value != null && model.value !== '') {
            return [String(provider.value), modelId];
        }
    }
    return null;
}

/** The API stores only the selected model id, not the provider path. */
export function fromModelCascaderValue(path: CascaderPath | null): string | null {
    if (!path?.length) return null;
    return String(path[path.length - 1]);
}

/** Flatten a provider tree into Select rows. The provider name is the group title. */
export function toGroupedModelOptions(tree: ModelProviderNode[] | undefined): SelectOption[] {
    return (tree ?? []).flatMap((provider) =>
        (provider.children ?? [])
            .filter((model) => model.value != null && model.value !== '')
            .map((model) => ({
                value: String(model.value),
                label: model.label,
                group: provider.label,
            })),
    );
}

/** Select values are strings. Empty stored ids stay unselected. */
export function toModelSelectValue(value: unknown): string | null {
    if (value == null || value === '') return null;
    return String(value);
}

/** Match the model name or its provider, so a provider search still lists its models. */
export function filterModelOption(keyword: string, option: SelectOption): boolean {
    const query = keyword.trim().toLowerCase();
    if (!query) return true;
    return (
        option.label.toLowerCase().includes(query) ||
        (option.group ?? '').toLowerCase().includes(query)
    );
}
