import { Button, Select } from '@bisheng/ui';

import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover";
import { Outlined } from "bisheng-icons";
import { AlignCenter,AlignLeft,AlignRight,Bold,Italic } from "lucide-react";
import { useTranslation } from "react-i18next";

const FONT_SIZE_OPTIONS = [10, 12, 14, 16, 18, 20, 24, 28].map((v) => ({ value: v, label: String(v) }))
export interface TextFormatProps {
colorPicker?: React.ReactNode;
  fontSize: number
  setFontSize: (size: number) => void
  bold: boolean
  setBold: (bold: boolean) => void
  italic: boolean
  setItalic: (italic: boolean) => void
  strikethrough: boolean
  setStrikethrough: (strikethrough: boolean) => void
  align: "left" | "center" | "right"
  setAlign: (align: "left" | "center" | "right") => void
  color?: string
  setColor?: (color: string) => void,
  underline?: boolean
  setUnderline?: (underline: boolean) => void
}

export function TextFormat({
  fontSize,
  setFontSize,
  bold,
  setBold,
  italic,
  setItalic,
  align,
  setAlign,
  color = "#000000",
  setColor,
  colorPicker,
}: TextFormatProps) {

  const { t } = useTranslation("dashboard")
  const selectLabels = useSelectLabels()
  const alignOptions = [
    { value: "left", label: t("styleConfigPanel.textFormat.alignLeft"), icon: <AlignLeft className="w-3.5 h-3.5" /> },
    { value: "center", label: t("styleConfigPanel.textFormat.alignCenter"), icon: <AlignCenter className="w-3.5 h-3.5" /> },
    { value: "right", label: t("styleConfigPanel.textFormat.alignRight"), icon: <AlignRight className="w-3.5 h-3.5" /> },
  ]
  return (
    <div
      className="
      flex items-center
      w-[230px] h-8
      border rounded-md
      overflow-hidden
    "
    >

      <Select
        {...selectLabels}
        variant="ghost"
        size="small"
        className="w-[60px] mx-1"
        options={FONT_SIZE_OPTIONS}
        value={fontSize}
        onChange={(v) => { if (v != null) setFontSize(Number(v)) }}
        aria-label={t("styleConfigPanel.textFormat.fontSize")}
      />


      {setColor && (
        // The swatch opens a color picker, not a list of options: a popover, not a Select.
        <Popover>
          <PopoverTrigger asChild>
            <Button
              variant="text"
              color="default"
              size="small"
              className="mx-1"
              aria-label={t("styleConfigPanel.textFormat.color")}
            >
              <span
                className="size-4 rounded border shadow-sm"
                style={{ backgroundColor: color }}
              />
              <Outlined.Down className="size-3 text-text-3" />
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0 border-none shadow-none bg-transparent">
            {colorPicker}
          </PopoverContent>
        </Popover>

        //   <div className="relative shrink-0 mr-2">
        //   <Input
        //     type="color"
        //     className="absolute inset-0 opacity-0 cursor-pointer"
        //     value={color}
        //     onChange={(e) => setColor(e.target.value)}
        //   />
        //   <div
        //     className="w-6 h-6 rounded"
        //     style={{ backgroundColor: color }}
        //   />
        // </div>
      )}


      <Select
        {...selectLabels}
        variant="icon"
        size="small"
        className="mx-1"
        options={alignOptions}
        value={align}
        onChange={(v) => { if (v != null) setAlign(v as "left" | "center" | "right") }}
        aria-label={t("styleConfigPanel.textFormat.align")}
      />


      <div className="flex w-[88px] m-1 gap-1">
        <IconBtn active={bold} onClick={() => setBold(!bold)}>
          <Bold className="w-3.5 h-3.5" />
        </IconBtn>
        <IconBtn active={italic} onClick={() => setItalic(!italic)}>
          <Italic className="w-3.5 h-3.5" />
        </IconBtn>
        {/* <IconBtn active={underline} onClick={() => setUnderline(!underline)}>
          <Underline className="w-3 h-3" />
        </IconBtn>
        <IconBtn
          active={strikethrough}
          onClick={() => setStrikethrough(!strikethrough)}
        >
          <Strikethrough className="w-3 h-3" />
        </IconBtn> */}
      </div>
    </div>
  )

}


interface IconBtnProps {
  active?: boolean
  children: React.ReactNode
  onClick: () => void
}

function IconBtn({ active, children, onClick }: IconBtnProps) {
  return (
    <Button variant="text" size="small" onClick={onClick} className={`w-7 h-5 px-0 rounded-[3px] ${active ? "bg-blue-100 text-blue-600" : ""}`} color="default">
      {children}
    </Button>
  )
}





interface CollapsibleBlockProps {
  title: string
  children: React.ReactNode
  isOpen?: boolean
  collapsed: boolean
  onCollapse: () => void
  rightContent?: React.ReactNode
}

export function CollapsibleBlock({
  title, children, isOpen = false, collapsed, onCollapse, rightContent
}: CollapsibleBlockProps) {

  return (
    <div className="space-y-3">
      <div
        className="flex items-center justify-between bg-gray-50 dark:bg-gray-400 rounded-md h-[28px] w-[228px] cursor-pointer"
        onClick={onCollapse}
      >
        <div className="flex items-center">
          <div className="h-3 w-[3px] bg-blue-500 ml-2 rounded-[2px]"></div>
          <label className="text-sm font-medium text-black ml-2">{title}</label>
        </div>
        <div className="flex items-center gap-2 mr-2">
          {rightContent}
          {!isOpen && (
            <Button variant="text" size="medium" className="h-6 w-6" color="default" iconOnly>
              {collapsed ? <Outlined.Down className="h-4 w-4" /> : <Outlined.Up className="h-4 w-4" />}
            </Button>
          )}
        </div>
      </div>
      {(isOpen || !collapsed) && (
        <div className="w-[228px]">
          {children}
        </div>
      )}
    </div>
  )
}


interface FormBlockProps {
  label: string
  children: React.ReactNode
}

export function FormBlock({ label, children }: FormBlockProps) {
  return (
    <div className="space-y-2">
      <label className="text-sm font-medium">{label}</label>
      <div className="w-[228px]">
        {children}
      </div>
    </div>
  )
}
