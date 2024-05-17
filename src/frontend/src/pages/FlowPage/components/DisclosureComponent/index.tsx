import { Button } from "@/components/bs-ui/button";
import { ChevronRightIcon } from "@radix-ui/react-icons";
import { DisclosureComponentType } from "../../../../types/components";

export default function DisclosureComponent({
  button: { title, Icon, buttons = [], color },
  children,
  openDisc,
}: DisclosureComponentType & any) {

  return <Button variant="outline" className="">
    <div className="flex gap-2 text-[#111]">
      <Icon strokeWidth={1.5} size={20} />
      <span className="components-disclosure-title">{title}</span>
    </div>
    <div className="components-disclosure-div">
      {buttons.map((x, index) => (
        <button key={index} onClick={x.onClick}> {x.Icon} </button>
      ))}
      <div>
        <ChevronRightIcon className={`h-4 w-4 text-foreground`} />
      </div>
    </div>
  </Button>
}
