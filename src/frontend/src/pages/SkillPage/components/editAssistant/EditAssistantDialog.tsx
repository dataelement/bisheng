import { Button } from "@/components/bs-ui/button";
import { DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input, Textarea } from "@/components/bs-ui/input";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { useEffect, useState } from "react";

export default function EditAssistantDialog({ name, desc, onSave }) {

    // State for form fields
    const [formData, setFormData] = useState({ name: '', desc: '' });

    useEffect(() => {
        setFormData({ name, desc })
    }, [name, desc])
    // console.log(formData, name, desc);

    // State for errors
    const [errors, setErrors] = useState<any>({});

    // Validate form fields
    const validateField = (name, value) => {
        switch (name) {
            case 'name':
                if (!value) return '名称不可为空';
                if (value.length > 50) return '名称最多50个字符';
                return '';
            case 'desc':
                if (value.length > 1000) return '最多1000个字符';
                return '';
            default:
                return '';
        }
    };

    // Handle field change
    const handleChange = (e) => {
        const { name, value } = e.target;
        const error = validateField(name, value);

        setFormData(prev => ({ ...prev, [name]: value }));
        setErrors(prev => ({ ...prev, [name]: error }));
    };

    // Validate entire form
    const validateForm = () => {
        const formErrors = {};
        let isValid = true;

        Object.keys(formData).forEach(key => {
            const error = validateField(key, formData[key]);
            if (error) {
                formErrors[key] = error;
                isValid = false;
            }
        });

        setErrors(formErrors);
        return isValid;
    };

    const { message, toast } = useToast()
    // Handle form submission
    const handleSubmit = (e) => {
        e.preventDefault();
        const isValid = validateForm();
        // console.log('Form data:', errors);
        if (!isValid) return toast({
            title: '提示',
            variant: 'error',
            description: Object.keys(errors).map(key => errors[key]),
        })

        onSave(formData)

    };

    return <DialogContent className="sm:max-w-[625px]">
        <DialogHeader>
            <DialogTitle>编辑助手</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-8 py-6">
            <div className="">
                <label htmlFor="name" className="bisheng-label">助手名称<span className="bisheng-tip">*</span></label>
                <Input id="name" name="name" placeholder="给助手取一个名字" className="mt-2" value={formData.name} onChange={handleChange} />
                {errors.name && <p className="bisheng-tip mt-1">{errors.name}</p>}
            </div>
            <div className="">
                <label htmlFor="desc" className="bisheng-label">助手描述</label>
                <Textarea id="desc" name="desc" placeholder="介绍助手功能，描述在会话和助手页面可见" maxLength={1200} className="mt-2" value={formData.desc} onChange={handleChange} />
                {errors.desc && <p className="bisheng-tip mt-1">{errors.desc}</p>}
            </div>
        </div>
        <DialogFooter>
            <DialogClose>
                <Button variant="outline" className="px-11" type="button">取消</Button>
            </DialogClose>
            <Button type="submit" className="px-11" onClick={handleSubmit}>确认</Button>
        </DialogFooter>
    </DialogContent>
};
