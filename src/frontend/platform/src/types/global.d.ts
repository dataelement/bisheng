export { };

declare global {
    interface Window {
        SearchSkillsPage: any;
        errorAlerts: (errorList: string[]) => void
        _flow: any
    }

    const __VCONSOLE_ENABLED__: boolean;
}

declare module "*.png" {
    const content: any;
    export default content;
}


declare module "*.svg" {
    const content: any;
    export default content;
}
