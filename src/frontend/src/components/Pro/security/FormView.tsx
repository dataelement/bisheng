import { useTranslation } from "react-i18next"

export default function FormView({ data }) {
    const { t } = useTranslation();
    const map = {
        '1': t('build.builtinWordList'),
        '2': t('build.customWordList')
    };

    return (
        <div className="mb-4 px-6">
            <div className="flex items-center mb-4">
                <span className="bisheng-label">{t('build.reviewType')}：</span> 
                <span className="bg-gray-200 dark:bg-slate-900 px-2 rounded-xl text-xs">{t('build.sensitiveWordMatch')}</span>
            </div>
            <div className="flex items-center mb-4">
                <span className="bisheng-label">{t('build.wordListType')}：</span>
                <div className="inline">
                    {data.wordsType?.map((v, index) => <span key={index} className="mr-2 bg-gray-200 dark:bg-slate-900 px-2 rounded-xl text-xs">{map[v]}</span>)}
                </div>
            </div>
            <span className="bisheng-label">{t('build.autoReplyContent')}：</span>
            <div className="flex justify-center mt-4">
                <p className="h-[100px] w-full overflow-y-auto scrollbar-hide bg-background-login py-2 px-4">
                    {data.autoReply || t('build.defaultAutoReply')}</p>
            </div>
        </div>
    );
}