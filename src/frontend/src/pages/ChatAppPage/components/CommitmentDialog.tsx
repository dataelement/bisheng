import { Button } from '@/components/bs-ui/button';
import { Checkbox } from '@/components/bs-ui/checkBox';
import { SearchInput } from '@/components/bs-ui/input';
import { Label } from '@/components/bs-ui/label';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/bs-ui/select';
import { useToast } from '@/components/bs-ui/toast/use-toast';
import { locationContext } from '@/contexts/locationContext';
import { userContext } from '@/contexts/userContext';
import { commitmentApi, signCommitmentApi } from '@/controllers/API';
import { useContext, useEffect, useState } from 'react';

const loadCommitments = async () => {
    try {
        const response = await fetch('/statement/data.json');
        if (!response.ok) {
            throw new Error('Failed to fetch data');
        }
        return await response.json();
    } catch (error) {
        console.error('Failed to load commitments:', error);
        return { title: '', commitments: [] }; // 返回默认的数据结构
    }
};

const CommitmentDialog = ({ id }) => {
    const [checkedItems, setCheckedItems] = useState(Array(10).fill(false));
    const [finalCheck, setFinalCheck] = useState(false);
    const [commitmentsData, setCommitmentsData] = useState({ id: '', title: '', commitments: [] });
    const { message } = useToast()
    const { user } = useContext(userContext)
    const [currentTime] = useState(new Date().toLocaleDateString())
    const { appConfig } = useContext(locationContext)

    const handleCheckboxChange = (index) => {
        const newCheckedItems = [...checkedItems];
        newCheckedItems[index] = !newCheckedItems[index];
        setCheckedItems(newCheckedItems);
    };

    const handleFinalCheckboxChange = () => {
        setFinalCheck(!finalCheck);
    };

    const handleSubmit = () => {
        setFinished(true);
        message({
            description: '签署成功',
            variant: 'success',
        })
        signCommitmentApi(user.id, id, commitmentsData.id)
    };

    useEffect(() => {
        if (!appConfig.securityCommitment) return setFinished(true)
        const fetchData = async () => {
            // 获取用户在当前应用是否已经签署过承诺 res
            const [data, res] = await Promise.all([loadCommitments(), commitmentApi(user.id, id)]);
            setFinished(res.signed)
            const currentData = data.find(el => el.id === res.id)
            setCommitmentsData(currentData);
            // 初始化checkedItems的长度与commitments长度一致
            if (currentData.commitments.length > 0) {
                setCheckedItems(Array(currentData.commitments.length).fill(false));
                setFinalCheck(false);
            }
        };
        fetchData();
    }, [id, appConfig.securityCommitment]);

    const [finished, setFinished] = useState(false);
    if (finished) return null;

    return (
        <div className="absolute top-0 left-0 w-full h-full z-50 bg-[rgba(0,0,0,0.1)] flex items-center justify-center">
            <div className="w-[660px] max-w-[80%] bg-background-login shadow-md p-6 rounded-md">
                <div className="p-5 max-w-3xl mx-auto">
                    {/* 显示标题 */}
                    <h2 className="text-2xl font-bold mb-6 text-center">《{commitmentsData.title}》</h2>

                    {/* 渲染承诺列表，添加滚动条 */}
                    <div className="max-h-[50vh] overflow-y-auto mb-6 bg-gray-100 p-4">
                        {commitmentsData.commitments.map((commitment, index) => (
                            <div key={id + index} className="mb-4">
                                <p className="text-gray-700 mb-2">{commitment}</p>
                                <div className='flex items-center'>
                                    <Checkbox
                                        id={`commitment-${index}`}
                                        onCheckedChange={() => handleCheckboxChange(index)}
                                        className="mr-2"
                                    />
                                    <Label htmlFor={`commitment-${index}`}>承诺遵守</Label>
                                </div>
                            </div>
                        ))}
                    </div>

                    {/* 承诺人和承诺时间 */}
                    <div className="mb-4">
                        <p className="text-gray-700">承诺人：<span className="font-semibold">{user.user_name}</span></p>
                        <p className="text-gray-700">承诺时间：<span className="font-semibold">{currentTime}</span></p>
                    </div>

                    {/* 最终确认复选框 */}
                    <div className="mb-6 flex items-center">
                        <Checkbox
                            key={id}
                            id="agreet"
                            onCheckedChange={handleFinalCheckboxChange}
                            className="mr-2"
                        />
                        <Label htmlFor='agreet' className="text-gray-600">本人已认真阅读《{commitmentsData.title}》并承诺落实全部安全事项。</Label>
                    </div>

                    {/* 提交按钮 */}
                    <div className="text-center">
                        <Button
                            onClick={handleSubmit}
                            disabled={!checkedItems.every(item => item) || !finalCheck}
                        >
                            确认签署
                        </Button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default CommitmentDialog;



export const SelectCommitment = ({ value, onChange }) => {
    const { appConfig } = useContext(locationContext)
    const [options, setOptions] = useState([])

    useEffect(() => {
        const fetchData = async () => {
            const data = await loadCommitments()
            setOptions(data.map(el => ({ label: el.title, value: el.id })))
            if (!value) {
                onChange(data[0].id)
            }
        };
        appConfig.securityCommitment && fetchData();
    }, [value]);

    if (!appConfig.securityCommitment) return null

    return <Select value={value} onValueChange={(v) => onChange(v)}>
        <SelectTrigger >
            <SelectValue />
        </SelectTrigger>
        <SelectContent >
            <SelectGroup>
                {options.map(el => (
                    <SelectItem key={el.value} value={el.value}>{el.label}</SelectItem>
                ))}
            </SelectGroup>
        </SelectContent>
    </Select>
}