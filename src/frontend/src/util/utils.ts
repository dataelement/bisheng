export function classNames(...classes: Array<string>): string {
    return classes.filter(Boolean).join(" ");
}