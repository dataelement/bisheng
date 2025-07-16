// components/ToolSelectionPanel.tsx
import { Sheet, SheetContent, SheetTitle } from "@/components/bs-ui/sheet";
import { Button } from '../bs-ui/button';
import { useState, useRef, useEffect } from 'react';
import { LoadIcon } from "../bs-icons/loading";

const SopFormDrawer = ({
  isDrawerOpen,
  setIsDrawerOpen,
  isEditing,
  sopForm,
  setSopForm,
  handleSaveSOP
}) => {
  const [errors, setErrors] = useState({
    name: '',
    content: ''
  });
  const [charCount, setCharCount] = useState({
    name: 0,
    description: 0,
    content: 0
  });
  const nameInputRef = useRef(null);
  const contentInputRef = useRef(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // 各字段的最大字数限制
  const MAX_LENGTHS = {
    name: 500,      // 名称不超过500字
    description: 1000, // 描述不超过1000字
    content: 50000   // 详细内容不超过100000字
  };

  const validateForm = () => {
    const newErrors = {
      name: '',
      content: ''
    };
    let isValid = true;

    if (!sopForm.name.trim()) {
      newErrors.name = '名称不能为空';
      isValid = false;
    } else if (sopForm.name.length > MAX_LENGTHS.name) {
      newErrors.name = `名称不能超过${MAX_LENGTHS.name}字`;
      isValid = false;
    }

    if (!sopForm.content.trim()) {
      newErrors.content = '详细内容不能为空';
      isValid = false;
    } else if (sopForm.content.length > MAX_LENGTHS.content) {
      newErrors.content = `详细内容不能超过${MAX_LENGTHS.content}字`;
      isValid = false;
    }

    setErrors(newErrors);
    return isValid;
  };

  const handleInputChange = (field, value) => {
    // 限制输入长度
    if (value.length <= MAX_LENGTHS[field]) {
      setSopForm({ ...sopForm, [field]: value });
      setCharCount({ ...charCount, [field]: value.length });
      if (errors[field]) {
        setErrors({ ...errors, [field]: '' });
      }
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (isSubmitting) return;

    if (validateForm()) {
      setIsSubmitting(true);
      try {
        await handleSaveSOP();
      } catch (error) {
        console.error('保存失败:', error);
      } finally {
        setIsSubmitting(false);
      }
    }
  };

  useEffect(() => {
    if (isDrawerOpen) {
      setErrors({
        name: '',
        content: ''
      });
      setCharCount({
        name: sopForm.name.length,
        description: sopForm.description.length,
        content: sopForm.content.length
      });
    }
  }, [isDrawerOpen]);

  return (
    <Sheet open={isDrawerOpen} onOpenChange={setIsDrawerOpen}>
      <SheetContent className="sm:max-w-md">
        <div className="flex flex-col h-full">
          <div className="flex items-center justify-between px-4 py-6 border-b border-gray-200">
            <SheetTitle className="text-lg font-medium text-gray-900">
              {isEditing ? '编辑SOP' : '新建SOP'}
            </SheetTitle>
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="sop-name" className="block text-sm font-medium text-gray-700">
                  SOP名称<span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  id="sop-name"
                  ref={nameInputRef}
                  value={sopForm.name}
                  onChange={(e) => handleInputChange('name', e.target.value)}
                  className={`mt-1 block w-full border ${errors.name ? 'border-red-500' : 'border-gray-300'} rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-blue-500 focus:border-blue-500`}
                  placeholder="请输入SOP名称"
                />
                <div className="flex justify-between">
                  {errors.name && (
                    <p className="mt-1 text-sm text-red-600">{errors.name}</p>
                  )}
                  <p className={`text-xs ${charCount.name > MAX_LENGTHS.name ? 'text-red-500' : 'text-gray-500'} text-right`}>
                    {charCount.name}/{MAX_LENGTHS.name}
                  </p>
                </div>
              </div>

              <div>
                <label htmlFor="sop-description" className="block text-sm font-medium text-gray-700">
                  描述
                </label>
                <textarea
                  id="sop-description"
                  rows={3}
                  value={sopForm.description}
                  onChange={(e) => handleInputChange('description', e.target.value)}
                  className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-blue-500 focus:border-blue-500"
                  placeholder="请输入SOP描述"
                />
                <p className={`text-xs ${charCount.description > MAX_LENGTHS.description ? 'text-red-500' : 'text-gray-500'} text-right`}>
                  {charCount.description}/{MAX_LENGTHS.description}
                </p>
              </div>

              <div>
                <label htmlFor="sop-content" className="block text-sm font-medium text-gray-700">
                  详细内容<span className="text-red-500">*</span>
                </label>
                <textarea
                  id="sop-content"
                  ref={contentInputRef}
                  rows={6}
                  value={sopForm.content}
                  onChange={(e) => handleInputChange('content', e.target.value)}
                  className={`mt-1 block w-full border ${errors.content ? 'border-red-500' : 'border-gray-300'} rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-blue-500 focus:border-blue-500`}
                  placeholder="请输入SOP详细内容"
                />
                <div className="flex justify-between">
                  {errors.content && (
                    <p className="mt-1 text-sm text-red-600">{errors.content}</p>
                  )}
                  <p className={`text-xs ${charCount.content > MAX_LENGTHS.content ? 'text-red-500' : 'text-gray-500'} text-right`}>
                    {charCount.content}/{MAX_LENGTHS.content}
                  </p>
                </div>
              </div>

              <div className="flex-shrink-0 px-4 py-4 border-t border-gray-200 flex justify-end space-x-3">
                <Button type="button" variant='outline' onClick={() => setIsDrawerOpen(false)}>取消</Button>
                {/* <Button type="submit">{isEditing ? '更新' : '创建'}</Button> */}
                <Button
                  type="submit"
                  disabled={isSubmitting}
                >
                  {isSubmitting ? (
                    <>
                      <LoadIcon className="animate-spin mr-2" />
                      保存中...
                    </>
                  ) : (
                    '保存'
                  )}
                </Button>
              </div>
            </form>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
};
export default SopFormDrawer;