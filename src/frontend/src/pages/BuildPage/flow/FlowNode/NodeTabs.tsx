import { Tabs, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";

export default function NodeTabs({ data, onChange }) {


    return <Tabs defaultValue={data.value} className="w-full" onValueChange={onChange}>
        <TabsList className="w-full flex">
            {data.options.map(option =>
                <TabsTrigger className="flex-1" key={option.key} value={option.key}>{option.label}</TabsTrigger>
            )}
        </TabsList>
    </Tabs>
}