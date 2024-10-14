import { Input } from "@/components/bs-ui/input";

// 节点表单项
export default function Parameter({ type }) {

    // 渲染逻辑根据 `type` 返回不同的组件
    switch (type) {
        case 'var_str':
            return <div className="mb-2">
                <span className="text-gray-600 text-sm">Input</span>
                <Input className="h-8" />
            </div>;
        // case 'know':
        //     return <NumberParameter />;
        // case 'date':
        //     return <DateParameter />;
        // case 'boolean':
        //     return <BooleanParameter />;
        default:
            return <div>Unsupported parameter type</div>;
    }
};
