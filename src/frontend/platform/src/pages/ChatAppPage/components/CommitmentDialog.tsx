import { Button } from '@/components/bs-ui/button';
import { Checkbox } from '@/components/bs-ui/checkBox';
import { SearchInput } from '@/components/bs-ui/input';
import { Label } from '@/components/bs-ui/label';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/bs-ui/select';
import { useToast } from '@/components/bs-ui/toast/use-toast';
import { locationContext } from '@/contexts/locationContext';
import { userContext } from '@/contexts/userContext';
import { getCommitmentApi, signCommitmentApi } from '@/controllers/API';
import { useContext, useEffect, useMemo, useState } from 'react';

const loadCommitments = async () => {
    try {
        const response = await fetch(__APP_ENV__.BASE_URL + '/statement/data.json');
        if (!response.ok) {
            throw new Error('Failed to fetch data');
        }
        return await response.json();
    } catch (error) {
        console.error('Failed to load commitments:', error);
        return { title: '', commitments: [] }; // 返回默认的数据结构
    }
};

const CommitmentDialog = ({ id, name }) => {
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
        signCommitmentApi({
            business_id: id,
            business_name: name,
            promise_id: commitmentsData.id,
            promise_name: commitmentsData.title
        })
        message({
            description: '签署成功',
            variant: 'success',
        })
    };

    useEffect(() => {
        if (!appConfig.securityCommitment) return setFinished(true)
        const fetchData = async () => {
            // 获取用户在当前应用是否已经签署过承诺 res
            const [data, res] = await Promise.all([loadCommitments(), getCommitmentApi(id)]);
            if (res.length === 0) return setFinished(true)
            const currentData = data.find(el => el.id === res[0].promise_id)
            if (!currentData) {
                console.error('未找到对应的承诺书')
                return setFinished(true)
            }
            setFinished(res[0].write)
            setCommitmentsData(currentData);
            // 初始化checkedItems的长度与commitments长度一致
            if (currentData.commitments.length > 0) {
                setCheckedItems(Array(currentData.commitments.length).fill(false));
                setFinalCheck(false);
            }
        };
        fetchData();
    }, [id, appConfig.securityCommitment]);

    const [finished, setFinished] = useState(true);
    if (finished) return null;

    return (
        <div className="absolute top-0 left-0 w-full h-full z-20 bg-[rgba(0,0,0,0.1)] flex items-center justify-center px-4">
            <div className="w-full max-w-[660px] bg-background-login shadow-md rounded-md sm:p-6">
                <div className="p-5 max-w-3xl mx-auto">
                    {/* Display Title */}
                    <h2 className="sm:text-2xl text-base font-bold mb-6 text-center">{`《${commitmentsData.title}》`}</h2>

                    {/* Commitment List with Scroll */}
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

                    {/* Commitment Person and Time */}
                    <div className="mb-4">
                        <p className="text-gray-700">承诺人：<span className="font-semibold">{user.user_name}</span></p>
                        <p className="text-gray-700">承诺时间：<span className="font-semibold">{currentTime}</span></p>
                    </div>

                    {/* Final Confirmation Checkbox */}
                    <div className="mb-6 flex items-center">
                        <Checkbox
                            key={id}
                            id="agreet"
                            onCheckedChange={handleFinalCheckboxChange}
                            className="mr-2"
                        />
                        <Label htmlFor='agreet' className="text-gray-600">本人已认真阅读《{commitmentsData.title}》并承诺落实全部安全事项。</Label>
                    </div>

                    {/* Submit Button */}
                    <div className="text-center">
                        <Button
                            onClick={handleSubmit}
                            disabled={!checkedItems.every(item => item) || !finalCheck}
                            className="w-full sm:w-auto"
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

    const _value = useMemo(() => value || 'x', [value])

    useEffect(() => {
        const fetchData = async () => {
            const data = await loadCommitments()
            const _options = data.map(el => ({ label: el.title, value: el.id }))
            setOptions([{ label: '无', value: 'x' }, ..._options])
            if (!value) {
                onChange('')
            }
        };
        appConfig.securityCommitment && options.length === 0 && fetchData();
    }, [value]);

    if (!appConfig.securityCommitment) return null

    return <Select value={_value} onValueChange={(v) => onChange(v === 'x' ? '' : v)}>
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