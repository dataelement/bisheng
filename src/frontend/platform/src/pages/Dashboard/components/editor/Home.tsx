import { useEditorDashboardStore } from "@/store/dashboardStore"
import { ChartItems } from "./ComponentPicker"
import { cn } from "@/utils"
import { ChartType } from "../../types/dataConfig"
import { useTranslation } from "react-i18next"

export default function Home() {
    const { t } = useTranslation("dashboard")
    const { addComponentToLayout } = useEditorDashboardStore()

    const handleItemClick = (item) => {
        addComponentToLayout({
            title: t(`chart.${item.label}`),
            type: item.type
        })
    }

    return (
        <div className="h-full bg-background flex items-center justify-center p-8">
            <div className="w-full max-w-[720px]">
                {/* Header */}
                <div className="text-center mb-10">
                    <h1 className="text-lg text-foreground font-medium">
                        {t('selectComponentToStart')}
                    </h1>
                </div>

                {/* Chart Grid */}
                <div className="flex justify-center flex-wrap gap-4">
                    {ChartItems.map((item) => (
                        <div
                            key={item.type}
                            onClick={() => handleItemClick(item)}
                            className={cn('w-[88px] h-[86px] flex flex-col items-center justify-center border rounded-md shadow-sm hover:shadow-lg transition-colors cursor-pointer',
                                item.type === ChartType.GroupedHorizontalBar && 'mr-10',
                                item.type === ChartType.Bar && 'ml-10',
                            )}>
                            <img src={`${__APP_ENV__.BASE_URL}/assets/dashboard/${item.type}.png`} className="w-8 h-8 mb-2" />
                            <span className="text-[12px] text-gray-600 whitespace-nowrap">{t(`chart.${item.label}`)}</span>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}
