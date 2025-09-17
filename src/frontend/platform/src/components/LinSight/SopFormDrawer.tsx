// components/ToolSelectionPanel.tsx
import { Sheet, SheetContent, SheetTitle } from "@/components/bs-ui/sheet";
import { Button } from '../bs-ui/button';
import { useState, useRef, useEffect } from 'react';
import { LoadIcon } from "../bs-icons/loading";
import { Input, Textarea } from "../bs-ui/input";
import SopMarkdown from "./SopMarkdown";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { t } from "i18next";
import { useTranslation } from "react-i18next";

const SopFormDrawer = ({
  isDrawerOpen,
  setIsDrawerOpen,
  isEditing,
  sopForm,
  setSopForm,
  tools,
  handleSaveSOP
}) => {
  const { t } = useTranslation()
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
  const { toast } = useToast()
  const validateForm = () => {
    const newErrors = {
      name: '',
      content: ''
    };
    let isValid = true;

    if (!sopForm.name.trim()) {
      newErrors.name = t('sopForm.nameRequired');
      isValid = false;
    } else if (sopForm.name.length > MAX_LENGTHS.name) {
      newErrors.name = t('sopForm.nameMaxLength', { max: MAX_LENGTHS.name });
      isValid = false;
    }

    if (!sopForm.content.trim()) {
      newErrors.content = t('sopForm.contentRequired');
      isValid = false;
    } else if (sopForm.content.length > MAX_LENGTHS.content) {
      newErrors.content = t('sopForm.contentMaxLength', { max: MAX_LENGTHS.content });
      isValid = false;
    }

    setErrors(newErrors);
    return isValid;
  };

  const handleInputChange = (field, value) => {
    // 计算实际内容长度（去除Markdown标记字符）
    const rawContent = field === 'content'
      ? value.replace(/[#*_\-`~\[\]()]/g, '')
      : value;
    const length = rawContent.length;

    // 更新表单值
    setSopForm(prev => ({ ...prev, [field]: value }));
    setCharCount(prev => ({ ...prev, [field]: length }));

    // 检查长度限制并设置错误状态
    if (length > MAX_LENGTHS[field]) {
      setErrors(prev => ({
        ...prev,
        [field]: field === 'content' 
          ? t('sopForm.contentMaxLength', { max: MAX_LENGTHS[field] })
          : t('sopForm.nameMaxLength', { max: MAX_LENGTHS[field] })
      }));
    } else if (errors[field]) {
      // 清除错误
      setErrors(prev => ({ ...prev, [field]: '' }));
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (isSubmitting) return;
    // toast({
    //   variant: 'error',
    //   title: t('sopForm.importFailed'),
    //   description: `${sopForm.name}${t('sopForm.contentTooLong')}`
    // })
    if (validateForm()) {
      setIsSubmitting(true);

      try {
        await handleSaveSOP();
      } catch (error) {
        console.error(t('sopForm.saveFailed'), error);
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
      <SheetContent
        className="w-[40%]"
        style={{ minWidth: '40%', maxWidth: '40%' }}
      >
        <div className="flex flex-col ">
          <div className="flex items-center justify-between px-4 pt-5 border-gray-200">
            <SheetTitle className="text-lg font-medium text-gray-900">
              {isEditing ? t('sopForm.editManual') : t('components.sopForm.createManual')}
            </SheetTitle>
          </div>
          <div className="flex-1 px-4 pb-4 pt-3">
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="sop-name" className="block text-sm font-medium pb-1 text-gray-700">
                  {t('sopForm.manualName')}<span className="text-red-500">*</span>
                </label>
                < Input
                  type="text"
                  showCount
                  maxLength={500}
                  id="sop-name"
                  ref={nameInputRef}
                  value={sopForm.name}
                  onChange={(e) => handleInputChange('name', e.target.value)}
                  className={`mt-1 block w-full border ${errors.name ? 'border-red-500' : 'border-gray-300'} rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-blue-500 focus:border-blue-500 text-[16px]`}
                  placeholder={t('sopForm.namePlaceholder')}
                />
                <div className="flex justify-between">
                  {errors.name && (
                    <p className="mt-1 text-sm text-red-600">{errors.name}</p>
                  )}
                </div>
              </div>

              <div>
                <label htmlFor="sop-description" className="block text-sm pb-1 font-medium text-gray-700">
                  {t('sopForm.description')}
                </label>
                <Textarea
                  id="sop-description"
                  maxLength={1000}
                  rows={3}
                  value={sopForm.description}
                  onChange={(e) => handleInputChange('description', e.target.value)}
                  className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-blue-500 focus:border-blue-500 text-[16px]"
                  placeholder={t('sopForm.descriptionPlaceholder')}
                />
              </div>

              <div>
                <label htmlFor="sop-content" className="h-full block text-sm pb-1 font-medium text-gray-700">
                  {t('sopForm.detailedContent')}<span className="text-red-500">*</span>
                </label>
                {isDrawerOpen && (
                  <div className="relative mt-1">
                    <SopMarkdown
                      tools={tools}
                      defaultValue={sopForm.content}
                      onChange={(val) => handleInputChange('content', val)}
                      className="h-full text-lg"
                    />
                    <div className="absolute bottom-0 right-0 bg-white/80 px-2 py-1 rounded text-xs text-gray-500">
                      {charCount.content}/{MAX_LENGTHS.content}
                    </div>
                  </div>
                )}
                {/* <Textarea
                  id="sop-content"
                  maxLength={50000}
                  ref={contentInputRef}
                  rows={6}
                  value={sopForm.content}
                  onChange={(e) => handleInputChange('content', e.target.value)}
                  className={`mt-1 block w-full border ${errors.content ? 'border-red-500' : 'border-gray-300'} rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-blue-500 focus:border-blue-500`}
                  placeholder={t('sopForm.contentPlaceholder')}
                /> */}
                <div className="flex justify-between">
                  {errors.content && (
                    <p className="mt-0 text-sm text-red-600">{errors.content}</p>
                  )}

                </div>
              </div>

              <div className="flex-shrink-0 px-4 py-2 border-t border-gray-200 flex justify-end space-x-3">
                <Button type="button" variant='outline' onClick={() => setIsDrawerOpen(false)}>{t('sopForm.cancel')}</Button>
                <Button
                  type="submit"
                  onClick={handleSubmit}
                  disabled={isSubmitting}
                >
                  {isSubmitting ? (
                    <>
                      <LoadIcon className="animate-spin mr-2" />
                      {t('sopForm.saving')}
                    </>
                  ) : (
                    t('sopForm.save')
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