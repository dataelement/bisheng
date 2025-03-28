import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import AppUseLog from "./useAppLog";
import { Button } from "@/components/bs-ui/button";
import { TableIcon } from "lucide-react";
import StatisticsReport from "./StatisticsReport";

export default function Index() {
    const { t } = useTranslation();
    const [showPage, setShowPage] = useState(null);

    const handleButtonClick = (page) => {
        setShowPage(page);
    };

    const [reportFilter, setReportFilter] = useState(null)
    if (showPage === 'statisticsReport') {
        return <StatisticsReport onBack={() => setShowPage(null)} onJump={setReportFilter} />;
    }

    return (
        <div id="model-scroll" className="w-full h-full px-2 pt-4 relative">

            {/* Default tab content when no page is selected */}
            <Tabs defaultValue="app" className="w-full mb-[40px]" onValueChange={e => { }}>
                <TabsList>
                    <TabsTrigger value="app">{t('operation.appUsageRecord')}</TabsTrigger>
                </TabsList>
                <TabsContent value="app">
                    {/* Buttons for page navigation */}
                    <div className="absolute top-4 right-4 space-x-4">
                        <Button
                            variant="outline"
                            className="btn btn-primary"
                            onClick={() => handleButtonClick('statisticsReport')}
                        >
                            <TableIcon className="size-4 mr-0.5" />
                            统计报表
                        </Button>
                    </div>
                    <AppUseLog initFilter={reportFilter} clearFilter={() => setReportFilter(null)} />
                </TabsContent>
            </Tabs>
        </div>
    );
}
