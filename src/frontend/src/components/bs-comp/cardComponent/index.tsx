import { useState } from "react";
import { DelIcon } from "../../bs-icons/del";
import { GoIcon } from "../../bs-icons/go";
import { PlusIcon } from "../../bs-icons/plus";
import { SettingIcon } from "../../bs-icons/setting";
import { SkillIcon } from "../../bs-icons/skill";
import { UserIcon } from "../../bs-icons/user";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "../../bs-ui/card";
import { Switch } from "../../ui/switch";
import { AddToIcon } from "../../bs-icons/addTo";
import { cname } from "@/components/bs-ui/utils";

interface IProps<T> {
  data: T,
  /** id为''时，表示新建 */
  id?: number | string,
  type: "skill" | "sheet" | "assist" | "setting", // 技能列表｜侧边弹窗列表
  title: string,
  edit?: boolean,
  description: React.ReactNode | string,
  checked?: boolean,
  user?: string,
  isAdmin?: boolean,
  footer?: React.ReactNode,
  onClick?: () => void,
  onAddTemp?: (data: T) => void,
  onCheckedChange?: (b: boolean, data: T) => Promise<any>
  onDelete?: (data: T) => void,
  onSetting?: (data: T) => void,
}

const gradients = [
  'bg-amber-500',
  'bg-orange-600',
  'bg-teal-500',
  'bg-purple-600',
  'bg-blue-700'
]

// 'bg-slate-600',
// 'bg-amber-500',
// 'bg-red-600',
// 'bg-orange-600',
// 'bg-teal-500',
// 'bg-purple-600',
// 'bg-blue-700',
// 'bg-yellow-600',
// 'bg-emerald-600',
// 'bg-green-700',
// 'bg-cyan-600',
// 'bg-sky-600',
// 'bg-indigo-600',
// 'bg-violet-600',
// 'bg-purple-600',
// 'bg-fuchsia-700',
// 'bg-pink-600',
// 'bg-rose-600'
export function TitleIconBg({ id, className = '', children = <SkillIcon /> }) {
  return <div className={cname(`rounded-sm flex justify-center items-center ${gradients[parseInt(id + '', 16) % gradients.length]}`, className)}>{children}</div>
}


export default function CardComponent<T>({
  id = '',
  data,
  type,
  edit = false,
  user,
  title,
  checked,
  isAdmin,
  description,
  footer = null,
  onClick,
  onDelete,
  onAddTemp,
  onCheckedChange,
  onSetting
}: IProps<T>) {

  const [_checked, setChecked] = useState(checked)

  const handleCheckedChange = async (bln) => {
    const res = await onCheckedChange(bln, data)
    if (res === false) return
    setChecked(bln)
  }

  // 新建卡片
  if (!id) return <Card className="group w-[320px] cursor-pointer border-dashed border-[#BEC6D6] transition hover:border-primary hover:shadow-none bg-transparent" onClick={onClick}>
    <CardHeader>
      <div className="flex justify-between pb-2"><PlusIcon className="group-hover:text-primary transition-none" /></div>
      <CardTitle className="">{title}</CardTitle>
    </CardHeader>
    <CardContent className="h-[140px] overflow-auto scrollbar-hide">
      <CardDescription>{description}</CardDescription>
    </CardContent>
    <CardFooter className="flex justify-end h-10">
      <div className="rounded cursor-pointer"><GoIcon className="group-hover:text-primary transition-none" /></div>
    </CardFooter>
  </Card>


  // 侧边弹窗列表
  if (type === 'sheet') return <Card className="group w-[320px] cursor-pointer bg-gray-100 hover:bg-gray-200 hover:shadow-none" onClick={onClick}>
    <CardHeader className="pb-2">
      <CardTitle>
        <div className="flex gap-2 pb-2 items-center">
          <TitleIconBg id={id}></TitleIconBg>
          <p className=" align-middle">{title}</p>
        </div>
        {/* <span></span> */}
      </CardTitle>
    </CardHeader>
    <CardContent className="h-[60px] overflow-auto scrollbar-hide mb-2">
      <CardDescription>{description}</CardDescription>
    </CardContent>
    <CardFooter className=" block">
      {footer}
    </CardFooter>
  </Card>


  // 技能组件
  return <Card className="group w-[320px] cursor-pointer" onClick={onClick}>
    <CardHeader>
      <div className="flex justify-between pb-2">
        <TitleIconBg id={id}></TitleIconBg>
        {edit && <Switch checked={_checked} onCheckedChange={handleCheckedChange} onClick={e => e.stopPropagation()}></Switch>}
      </div>
      <CardTitle className="">{title}</CardTitle>
    </CardHeader>
    <CardContent className="h-[140px] overflow-auto scrollbar-hide">
      <CardDescription>{description}</CardDescription>
    </CardContent>
    <CardFooter className="flex justify-between h-10">
      <div className="flex gap-1 items-center">
        <UserIcon />
        <span className="text-sm text-muted-foreground">创建用户</span>
        <span className="text-sm font-medium leading-none">{user}</span>
      </div>
      {edit
        && <div className="hidden group-hover:flex">
          <div className="hover:bg-[#EAEDF3] rounded cursor-pointer" onClick={(e) => { e.stopPropagation(); onSetting(data) }}><SettingIcon /></div>
          {isAdmin && type === 'skill' && <div className="hover:bg-[#EAEDF3] rounded cursor-pointer" onClick={(e) => { e.stopPropagation(); onAddTemp(data) }}><AddToIcon /></div>}
          <div className="hover:bg-[#EAEDF3] rounded cursor-pointer" onClick={(e) => { e.stopPropagation(); onDelete(data) }}><DelIcon /></div>
        </div>
      }
    </CardFooter>
  </Card>
};
