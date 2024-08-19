import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import Flies from "./components/Flies";
import Header from "./components/Header";
import Paragraphs from "./components/Paragraphs";

export default function FilesPage() {

    return <div className="size-full px-2 py-4 relative bg-background-login">
        {/* title */}
        <Header />
        {/* tab */}
        <Tabs defaultValue="file" className="mt-4">
            <TabsList className="">
                <TabsTrigger value="file" className="roundedrounded-xl">文件管理</TabsTrigger>
                <TabsTrigger value="paragraph">分段管理</TabsTrigger>
            </TabsList>
            <TabsContent value="file">
                <Flies />
            </TabsContent>
            <TabsContent value="paragraph">
                <Paragraphs />
            </TabsContent>
        </Tabs>
    </div>
};
