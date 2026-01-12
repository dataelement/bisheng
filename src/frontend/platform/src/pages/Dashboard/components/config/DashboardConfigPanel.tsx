// DashboardConfigPanel.tsx
"use client"

import { Button } from "@/components/bs-ui/button"
import { ChevronLeft, ChevronRight } from "lucide-react"
import { useEffect, useState } from "react"
import { useEditorDashboardStore } from "@/store/dashboardStore"
import { useTranslation } from "react-i18next"

interface DashboardConfigPanelProps {
  collapsed?: boolean
  onCollapse?: () => void
}

export function DashboardConfigPanel({ collapsed = false, onCollapse }: DashboardConfigPanelProps) {
  const { currentDashboard, updateCurrentDashboard } = useEditorDashboardStore()
  const [dashboardTheme, setDashboardTheme] = useState<'light' | 'dark'>(() => {
    // 从当前仪表盘获取主题
    return currentDashboard?.style_config?.theme as 'light' | 'dark' || 'light'
  })
  const { t } = useTranslation("dashboard")

  // 当仪表盘变化时更新主题状态
  useEffect(() => {
    if (currentDashboard?.style_config?.theme) {
      setDashboardTheme(currentDashboard.style_config.theme as 'light' | 'dark')
    }
  }, [currentDashboard])

  const handleThemeChange = (theme: 'light' | 'dark') => {
    setDashboardTheme(theme)

    // 更新仪表盘主题
    if (currentDashboard) {
      const updatedDashboard = {
        ...currentDashboard,
        style_config: {
          ...currentDashboard.style_config,
          theme: theme
        }
      }
      updateCurrentDashboard(updatedDashboard)
    }
  }

  const PanelHeader = ({ title, onCollapse, icon }: any) => (
    <div className="px-4 py-3 border-b flex items-center justify-between bg-muted/20">
      <h3 className="text-base font-semibold">{title}</h3>
      <Button variant="ghost" size="icon" onClick={onCollapse} className="h-8 w-8">
        {icon}
      </Button>
    </div>
  )

  const CollapseLabel = ({ label, onClick, icon }: any) => (
    <div className="h-full flex flex-col items-center justify-center cursor-pointer hover:bg-accent/50 transition-colors" onClick={onClick}>
      <div className="writing-mode-vertical text-sm font-medium py-4">{label}</div>
      <div className="mt-2">{icon}</div>
    </div>
  )

  return (
    <div className="h-full flex bg-background border-l border-border">
      <div className={`border-r flex flex-col h-full transition-all duration-300 ${collapsed ? "w-12" : "w-[460px]"} shrink-0`}>
        {collapsed ? (
          <CollapseLabel
            label={t("configPanel.title")}
            onClick={onCollapse}
            icon={<ChevronRight />}
          />
        ) : (
          <div className="flex-1 flex flex-col overflow-hidden">
            <PanelHeader
              title={t("configPanel.title")}
              onCollapse={onCollapse}
              icon={<ChevronLeft />}
            />

            <div className="flex-1 overflow-y-auto px-2 pb-6 pt-4 space-y-6">
              {/* 仪表盘风格选择 */}
              <div className="space-y-2">
                <label className="text-sm font-medium">
                  {t("configPanel.dashboardStyle")}
                </label>
                <div className="grid grid-cols-2 gap-4">
                  {/* 浅色主题 */}
                  <div
                    className={`border rounded-lg p-3 cursor-pointer transition-all ${dashboardTheme === 'light' ? 'border-primary ring-2 ring-primary/20 bg-primary/5' : 'border-gray-200 hover:border-gray-300'}`}
                    onClick={() => handleThemeChange('light')}
                  >
                    <div className="aspect-square bg-gradient-to-br from-gray-50 h-[96px] w-[180px] to-gray-100 rounded border mb-2">
                      <img src={`${__APP_ENV__.BASE_URL}/assets/dashboard/light.png`} alt="" />
                    </div>
                    <div className="flex items-center justify-center">
                      <span className={`text-sm ${dashboardTheme === 'light' ? 'text-primary font-medium' : ''}`}>{t("configPanel.lightTheme")}</span>
                    </div>
                  </div>

                  {/* 深色主题 */}
                  <div
                    className={`border rounded-lg p-3 cursor-pointer transition-all ${dashboardTheme === 'dark' ? 'border-primary ring-2 ring-primary/20 bg-primary/5' : 'border-gray-200 hover:border-gray-300'}`}
                    onClick={() => handleThemeChange('dark')}
                  >
                    <div className="aspect-square bg-gradient-to-br  h-[96px] w-[180px] from-gray-800 to-gray-900 rounded border mb-2">
                      <img src={`${__APP_ENV__.BASE_URL}/assets/dashboard/dark.png`} alt="" />
                    </div>
                    <div className="flex items-center justify-center">
                      <span className={`text-sm ${dashboardTheme === 'dark' ? 'text-primary font-medium' : ''}`}>{t("configPanel.darkTheme")}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}