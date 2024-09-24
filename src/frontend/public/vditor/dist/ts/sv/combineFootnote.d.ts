/**
 * 合并脚注
 * @param elements vditor.sv.element
 * @param afterCombine 每个脚注块合并完成后的回调, param: root为合并后的脚注块
 */
export declare const combineFootnote: (elements: HTMLElement, afterCombine?: (root: HTMLElement) => void) => void;
