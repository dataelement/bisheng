import { Tabs, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";

export default function NodeTabs({ data, onChange }) {


    return <Tabs defaultValue={data.value} className="w-full px-3" onValueChange={onChange}>
        <TabsList className="w-full flex">
            {data.options.map(option =>
                <TabsTrigger className="flex-1" key={option.key} value={option.key}>
                    {option.label}
                    {option.help && <QuestionTooltip content={option.help} />}
                </TabsTrigger>
            )}
        </TabsList>
    </Tabs>
}