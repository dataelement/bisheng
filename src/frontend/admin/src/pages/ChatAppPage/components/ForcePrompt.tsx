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
    const checkPrompted = (id: string): boolean => {
        const str = localStorage.getItem("force_chat_prompt");
        if (!str) return false;

        try {
            // 尝试将字符串解析为对象
            const map = JSON.parse(str);

            // 检查 id 是否存在于 map 中
            return !!map[id];
        } catch (error) {
            // 如果 JSON 解析失败，则返回 false
            console.error("Error parsing JSON from localStorage:", error);
            return false;
        }
    };

    useEffect(() => {
        setIsPrompted(appConfig.chatPrompt && !checkPrompted(id));
    }, [appConfig, id]);

    const handleOk = () => {
      try {
          const str = localStorage.getItem("force_chat_prompt");
          let map;

          if (str) {
              map = JSON.parse(str);
              // 验证 map 是否为对象
              if (typeof map !== "object") {
                  throw new Error("Invalid data format in local storage");
              }
          } else {
              map = {};
          }

          map[id] = true;
          localStorage.setItem("force_chat_prompt", JSON.stringify(map));
          setIsPrompted(false); // 关闭提示
      } catch (error) {
          console.error("Error occurred while handling local storage:", error);
      }
    };

    if (!isPrompted) return null;

    return (
        <div className="absolute top-0 left-0 w-full h-full z-50 bg-[rgba(0,0,0,0.1)] flex items-center justify-center">
            <div className="w-[600px] max-w-[80%] bg-background-login shadow-md text-center p-10 rounded-md">
                <div className="text-left break-all mb-10">
                    <p className="text-gray-950 dark:text-slate-50 mb-5 text-center">{t('chatTipsTitle')}</p>
                    {t('chatTips').split('\n').map((line, index) => (
                        <p className="text-md mb-1 text-gray-600 dark:text-slate-400" key={index}>{line}</p>
                    ))}
                </div>
                <Button className="text-slate-50" onClick={handleOk}>我知道了</Button>
            </div>
        </div>
    );
}
