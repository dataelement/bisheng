export function canConfigureBuiltinTool(actions: readonly string[] | undefined): boolean {
    return actions?.includes('edit') ?? false;
}
