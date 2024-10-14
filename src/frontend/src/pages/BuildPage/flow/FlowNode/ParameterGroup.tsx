import { Badge } from "@/components/bs-ui/badge";
import Parameter from "./Parameter";

export default function ParameterGroup() {

    return <div>
        <Badge variant="outline" className="border-gray-500 bg-[#fff]">LLM-23nj3</Badge>
        <Parameter type="var_str"/>

    </div>
};
