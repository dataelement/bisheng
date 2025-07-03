declare global {
    interface Window {
        MathJax: any;
    }
}
export declare const mathRender: (element?: (HTMLElement | Document), options?: {
    cdn?: string;
    math?: IMath;
}) => void;
