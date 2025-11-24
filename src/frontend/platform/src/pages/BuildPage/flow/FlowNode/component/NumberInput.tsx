import { useEffect, useState } from "react";

 function NumberInput({ value, onChange }) {
  const [inputValue, setInputValue] = useState(value === '' ? '0' : value || '0');
  const [error, setError] = useState('');

  // 同步外部值变化
  useEffect(() => {
    // 如果外部值为空，则显示0；否则显示实际值
    if (value === '' || value === undefined || value === null) {
      setInputValue('0');
       onChange('0');
    } else {
      setInputValue(String(value));
    }
  }, [value]);
  useEffect(() => {
      if (value === '' || value === undefined || value === null) {
        onChange('0');
      }
    }, []);
  // 验证数字范围
  const validateNumber = (numValue) => {
    // 空值或0都视为有效
    if (numValue === '' || numValue === '0') {
      return { isValid: true, value: '0' };
    }

    // 允许单独的负号
    if (numValue === '-') {
      return { isValid: true, value: '-' };
    }

    const number = Number(numValue);
    if (isNaN(number)) {
      return { isValid: false, error: '请输入有效的数字' };
    }

    // 检查32位整数范围 (-2^31 到 2^31-1)
    if (number < -4294967296 || number > 4294967296) {
      return { isValid: false, error: '数字大小不能超过2的32次方。' };
    }

    return { isValid: true, value: number };
  };

  // 处理输入变化
  const handleChange = (e) => {
    const newValue = e.target.value;
    setInputValue(newValue);
    
    // 如果清空输入，暂时不更新父组件，等失去焦点时处理
    if (newValue === '') {
      setError('');
      return;
    }

    // 允许单独的负号
    if (newValue === '-') {
      setError('');
      onChange('-');
      return;
    }

    const validation = validateNumber(newValue);
    if (validation.isValid) {
      setError('');
      onChange(String(validation.value));
    } else {
      setError(validation.error);
    }
  };

  // 处理失去焦点事件
  const handleBlur = () => {
    // 如果输入为空，设置为0
    if (inputValue === '') {
      setInputValue('0');
      setError('');
      onChange('0');
      return;
    }

    // 如果只有负号，设置为0
    if (inputValue === '-') {
      setInputValue('0');
      setError('');
      onChange('0');
      return;
    }

    const validation = validateNumber(inputValue);
    if (!validation.isValid) {
      // 如果无效，设置为0
      setInputValue('0');
      setError('');
      onChange('0');
    } else {
      // 确保格式正确
      const finalValue = String(validation.value);
      setInputValue(finalValue);
      onChange(finalValue);
    }
  };

  return (
    <div>
      <input
        type="number"
        value={inputValue}
        onChange={handleChange}
        onBlur={handleBlur}
     className={`w-full px-3 py-1 border rounded-md nodrag h-8 bg-gray-50 mb-2 ${
          error ? 'border-red-500 focus:border-red-500 focus:ring-red-500' : 'border-gray-300 focus:border-blue-500'
        }`}
        min="-4294967296"
        max="4294967295"
      />
      {error && <p className="fixed text-red-500 text-xs">{error}</p>}
    </div>
  );
}
export default NumberInput;