/**
 * App kinds shown in the app center and the app square (v3.1.0-alpha1 F001).
 *
 * The backend filters by `flow_type` (5 assistant, 10 workflow, 35 hosted app);
 * a type filter must go to the server, because both lists page on the server
 * and filtering a page client-side would leave empty pages with more to load.
 */
export const HOSTED_APP_FLOW_TYPE = 35;

export type AppTypeFilter = 'all' | 'hosted' | 'assistant' | 'workflow';

const FLOW_TYPE_BY_FILTER: Record<Exclude<AppTypeFilter, 'all'>, number> = {
  hosted: HOSTED_APP_FLOW_TYPE,
  assistant: 5,
  workflow: 10,
};

const LABEL_KEY_BY_FLOW_TYPE: Record<number, string> = {
  [HOSTED_APP_FLOW_TYPE]: 'com_app.type_hosted_app',
  5: 'com_app.type_assistant',
  10: 'com_app.type_workflow',
};

/** `flow_type` to send for a filter; `undefined` means "all types". */
export function flowTypeForFilter(filter: AppTypeFilter): number | undefined {
  return filter === 'all' ? undefined : FLOW_TYPE_BY_FILTER[filter];
}

/** i18n key of the card's type tag, or `null` for a kind that has no tag. */
export function appTypeLabelKey(flowType: number | string | undefined): string | null {
  return LABEL_KEY_BY_FLOW_TYPE[Number(flowType)] ?? null;
}

/** Filter options in display order; hosted apps only exist where the runtime layer is deployed. */
export function appTypeFilters(runtimeEnabled: boolean): AppTypeFilter[] {
  return runtimeEnabled ? ['all', 'hosted', 'assistant', 'workflow'] : ['all', 'assistant', 'workflow'];
}

export const APP_TYPE_FILTER_LABEL_KEY: Record<AppTypeFilter, string> = {
  all: 'com_app.type_all',
  hosted: 'com_app.type_hosted_app',
  assistant: 'com_app.type_assistant',
  workflow: 'com_app.type_workflow',
};
