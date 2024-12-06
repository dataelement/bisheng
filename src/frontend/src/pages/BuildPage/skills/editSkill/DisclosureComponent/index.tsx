import { DisclosureComponentType } from "@/types/components";
import { Disclosure } from "@headlessui/react";
import { ChevronRight } from "lucide-react";

export default function DisclosureComponent({
  button: { title, Icon, buttons = [], color },
  children,
  openDisc,
}: DisclosureComponentType & any) {
  return (
    <Disclosure as="div" key={title}>
      {({ open }) => (
        <>
          <div className="min-w-[108px]">
            <Disclosure.Button className="components-disclosure-arrangement">
              <div className="flex gap-2 text-[#111] dark:text-gray-50">
                <Icon strokeWidth={1.5} size={20} />
                <span className="components-disclosure-title">{title}</span>
              </div>
              <div className="components-disclosure-div">
                {buttons.map((x, index) => (
                  <button key={index} onClick={x.onClick}> {x.Icon} </button>
                ))}
                <div>
                  <ChevronRight className={`h-4 w-4 text-foreground`} />
                </div>
              </div>
            </Disclosure.Button>
          </div>
          <Disclosure.Panel as="div" static={openDisc}>
            {children}
          </Disclosure.Panel>
        </>
      )}
    </Disclosure>
  );
}
