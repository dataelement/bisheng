/// <reference types="./types" />
export declare class Toolbar {
    elements: {
        [key: string]: HTMLElement;
    };
    element: HTMLElement;
    constructor(vditor: IVditor);
    updateConfig(vditor: IVditor, options: IToolbarConfig): void;
    private genItem;
}
