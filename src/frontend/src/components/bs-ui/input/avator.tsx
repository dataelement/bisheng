import { Button } from "../button";
import { useToast } from "../toast/use-toast";
import { cname } from "../utils";

// 头像
export default function Avator({
    size = 5 * 1024 * 1024,
    accept = "image/jpeg,image/png",
    value,
    className,
    buttonName = '上传头像',
    onChange,
    children
}) {
    const { message } = useToast();

    const handleFileChange = (event) => {
        const file = event.target.files[0];
        if (file) {
            const isValidSize = file.size <= size;
            const isValidType = accept.split(',').some(type => file.type === type);

            const errormgs = []
            if (!isValidSize) errormgs.push(`文件大小不能超过 ${size / 1024 / 1024}MB`)
            if (!isValidType) errormgs.push(`文件类型不符合要求：${accept}`)

            errormgs.length ? message({
                variant: 'error',
                description: errormgs
            }) : onChange(file)
        }
    };

    return <div className={cname("flex w-full rounded-md gap-4", className)}>
        {value ? <img src={value} className="max-w-24 max-h-24 rounded-md object-cover" alt="" /> : children}
        <Button variant="outline" className="relative">
            {buttonName}
            <input
                className=" absolute top-0 left-0 inset-0 w-full h-full opacity-0 cursor-pointer"
                type="file"
                accept={accept}
                onChange={handleFileChange}
            />
        </Button>
    </div>
};
