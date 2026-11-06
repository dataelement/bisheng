import type { CascaderFilter, CascaderOption, CascaderPath, CascaderValue } from './types';

export interface CascaderEntry {
  key: string;
  path: CascaderPath;
  options: CascaderOption[];
}

export type ChildrenResolver = (option: CascaderOption, path: CascaderPath) => CascaderOption[] | undefined;

export function cascaderPathKey(path: CascaderPath): string {
  return JSON.stringify(path);
}

export function pathEquals(left: CascaderPath, right: CascaderPath): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

export function appendPath(path: CascaderPath, value: CascaderValue): CascaderPath {
  return [...path, value];
}

export function flattenCascader(
  options: CascaderOption[],
  getChildren: ChildrenResolver,
  selectableParents: boolean,
): CascaderEntry[] {
  const result: CascaderEntry[] = [];
  const visit = (items: CascaderOption[], parentPath: CascaderPath, parentOptions: CascaderOption[]) => {
    for (const option of items) {
      const path = appendPath(parentPath, option.value);
      const optionPath = [...parentOptions, option];
      const children = getChildren(option, path);
      const hasChildren = option.isLeaf === false || (children?.length ?? 0) > 0;
      if (!hasChildren || selectableParents) {
        result.push({ key: cascaderPathKey(path), path, options: optionPath });
      }
      if (children?.length) visit(children, path, optionPath);
    }
  };
  visit(options, [], []);
  return result;
}

export function resolveOptionPath(
  options: CascaderOption[],
  path: CascaderPath,
  getChildren: ChildrenResolver,
): CascaderOption[] {
  const result: CascaderOption[] = [];
  let items = options;
  for (let index = 0; index < path.length; index += 1) {
    const option = items.find((candidate) => candidate.value === path[index]);
    if (!option) return result;
    result.push(option);
    items = getChildren(option, path.slice(0, index + 1)) ?? [];
  }
  return result;
}

export function activePositionForPath(
  options: CascaderOption[],
  path: CascaderPath,
  getChildren: ChildrenResolver,
): { level: number; index: number } {
  let items = options;
  let position = { level: 0, index: 0 };
  for (let level = 0; level < path.length; level += 1) {
    const index = items.findIndex((option) => option.value === path[level]);
    if (index < 0) break;
    position = { level, index };
    items = getChildren(items[index], path.slice(0, level + 1)) ?? [];
  }
  return position;
}

export function defaultCascaderFilter(keyword: string, path: CascaderOption[]): boolean {
  const needle = keyword.trim().toLocaleLowerCase();
  if (!needle) return true;
  return path.some((option) => option.label.toLocaleLowerCase().includes(needle));
}

export function filterEntries(
  entries: CascaderEntry[],
  keyword: string,
  filter: boolean | CascaderFilter,
): CascaderEntry[] {
  if (!keyword || filter === false) return entries;
  const matcher = filter === true ? defaultCascaderFilter : filter;
  return entries.filter((entry) => matcher(keyword, entry.options));
}

export function descendantLeaves(
  option: CascaderOption,
  path: CascaderPath,
  getChildren: ChildrenResolver,
): CascaderEntry[] {
  const children = getChildren(option, path);
  if (!children?.length) return option.isLeaf === false ? [] : [{ key: cascaderPathKey(path), path, options: [option] }];
  const leaves: CascaderEntry[] = [];
  for (const child of children) {
    const childPath = appendPath(path, child.value);
    for (const entry of descendantLeaves(child, childPath, getChildren)) {
      leaves.push({ ...entry, options: [option, ...entry.options] });
    }
  }
  return leaves;
}
