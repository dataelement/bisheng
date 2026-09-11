/**
 * Selection-checkbox styling shared by the file-list toolbar (select-all), list
 * rows and cards. Keeping it in one place is what stops the three surfaces from
 * drifting apart: a neutral border while idle, brand border once the box is
 * checked or indeterminate.
 */
export const SELECTION_CHECKBOX_CLASS =
    "border-border-deep data-[state=checked]:border-primary data-[state=indeterminate]:border-primary";
