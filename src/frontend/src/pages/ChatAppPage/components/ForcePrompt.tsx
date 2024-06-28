import { Button } from "@/components/bs-ui/button";
import { locationContext } from "@/contexts/locationContext";
import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

// 强制提示组件
export default function ForcePrompt({ id }) {
    const { appConfig } = useContext(locationContext);
    const [isPrompted, setIsPrompted] = useState(false);
    const { t } = useTranslation()

    // 检查是否已经提示过
    const checkPrompted = (id) => {
        const str = localStorage.getItem("force_chat_prompt");
        if (!str) return false;
        const map = JSON.parse(str);
        return !!map[id];
    };

    useEffect(() => {
        setIsPrompted(appConfig.chatPrompt && !checkPrompted(id));
    }, [appConfig, id]);

    const handleOk = () => {
        const str = localStorage.getItem("force_chat_prompt");
        const map = str ? JSON.parse(str) : {};
        map[id] = true;
        localStorage.setItem("force_chat_prompt", JSON.stringify(map));
        setIsPrompted(false); // 关闭提示
    };

    if (!isPrompted) return null;

    return (
        <div className="absolute top-0 left-0 w-full h-full z-50 bg-[rgba(0,0,0,0.1)] flex items-center justify-center">
            <div className="w-[600px] max-w-[80%] bg-[#fff] shadow-md text-center p-10 rounded-md">
                <div className="text-left break-all mb-10">
                    <p className="text-gray-950 mb-5 text-center">{t('chatTipsTitle')}</p>
                    {t('chatTips').split('\n').map((line, index) => (
                        <p className="text-md mb-1 text-gray-600" key={index}>{line}</p>
                    ))}
                </div>
                <Button onClick={handleOk}>我知道了</Button>
            </div>
        </div>
    );
}
