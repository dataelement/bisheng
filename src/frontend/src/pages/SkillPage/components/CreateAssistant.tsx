import { useState } from "react";
import { Button } from "../../../components/bs-ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "../../../components/bs-ui/dialog";
import { Input, Textarea } from "../../../components/bs-ui/input";
import { LoadIcon } from "../../../components/bs-icons/loading";
import { useNavigate } from "react-router-dom";

export default function CreateAssistant() {

    // State for form fields
    const [formData, setFormData] = useState({
        name: '',
        roleAndTasks: ''
    });

    const [loading, setLoading] = useState(false);
    // State for errors
    const [errors, setErrors] = useState<any>({});

    // Validate form fields
    const validateField = (name, value) => {
        switch (name) {
            case 'name':
                if (!value) return '名称不可为空';
                if (value.length > 50) return '名称最多50个字符';
                return '';
            case 'roleAndTasks':
                if (value.length < 20) return '不能少于20个字符';
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

    // Handle form submission
    const navigate = useNavigate()
    const handleSubmit = (e) => {
        e.preventDefault();
        const isValid = validateForm();

        if (isValid) {
            console.log('Form data:', formData);
            setLoading(true)
            // Proceed with form submission (e.g., API call)
            // Reset form or show a success message

            setTimeout(() => {
                navigate('/assistant/1')
            }, 2000);
        }
    };

    return <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
            <DialogTitle>创建助手</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-6 py-6">
            <div className="">
                <label htmlFor="name" className="bisheng-label">助手名称<span className="bisheng-tip">*</span></label>
                <Input id="name" name="name" placeholder="给助手取一个名字" className="mt-2" value={formData.name} onChange={handleChange} />
                {errors.name && <p className="bisheng-tip mt-1">{errors.name}</p>}
            </div>
            <div className="">
                <label htmlFor="roleAndTasks" className="bisheng-label">你希望助手的角色是什么，具体完成什么任务？</label>
                <Textarea id="roleAndTasks" name="roleAndTasks" placeholder="例如助手的身份、完成任务的具体方法和步骤、回答问题时的语气以及应该注意什么问题等" maxLength={1000} className="mt-2" value={formData.roleAndTasks} onChange={handleChange} />
                {errors.roleAndTasks && <p className="bisheng-tip mt-1">{errors.roleAndTasks}</p>}
            </div>
        </div>
        <DialogFooter>
            <DialogClose>
                <Button variant="outline" className="px-10" type="button" onClick={() => setFormData({ name: '', roleAndTasks: '' })}>取消</Button>
            </DialogClose>
            <Button disabled={loading} type="submit" className="px-10" onClick={handleSubmit}>
                {loading && <LoadIcon className="mr-2" />}
                创建</Button>
        </DialogFooter>
    </DialogContent>
};
