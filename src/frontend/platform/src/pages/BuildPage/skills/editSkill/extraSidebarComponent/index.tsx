import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { alertContext } from "@/contexts/alertContext";
import { TabsContext } from "@/contexts/tabsContext";
import { typesContext } from "@/contexts/typesContext";
import L2ParamsModal from "@/modals/L2ParamsModal";
import { APIClassType, APIObjectType } from "@/types/api";
import { FlowType } from "@/types/flow";
import { getNodeNames, nodeColors, nodeIconsLucide } from "@/utils";
import { Menu, Search } from "lucide-react";
import { useContext, useState } from "react";
import { useTranslation } from "react-i18next";
import DisclosureComponent from "../DisclosureComponent";
import PersonalComponents from "./PersonalComponents";

export default function ExtraSidebar({ flow }: { flow: FlowType }) {
  const { t } = useTranslation()

  const { data } = useContext(typesContext);
  const { saveFlow } = useContext(TabsContext);
  const { setSuccessData } = useContext(alertContext);
  const [dataFilter, setFilterData] = useState(data);
  const [search, setSearch] = useState("");

  const [open, setOpen] = useState(false)

  function onDragStart(
    event: React.DragEvent<any>,
    data: { type: string; node?: APIClassType }
  ) {
    // start drag event
    var crt = event.currentTarget.cloneNode(true);
    crt.style.position = "absolute";
    crt.style.top = "-500px";
    crt.style.right = "-500px";
    crt.classList.add("cursor-grabbing");
    document.body.appendChild(crt);
    event.dataTransfer.setDragImage(crt, 0, 0);
    event.dataTransfer.setData("nodedata", JSON.stringify(data));
  }

  function handleSearchInput(e: string) {
    setFilterData((_) => {
      let ret = {};
      Object.keys(data).forEach((d: keyof APIObjectType, i) => {
        ret[d] = {};
        let keys = Object.keys(data[d]).filter((nd) =>
          nd.toLowerCase().includes(e.toLowerCase())
        );
        keys.forEach((element) => {
          ret[d][element] = data[d][element];
        });
      });
      return ret;
    });
  }

  const nodeNames = getNodeNames()
  return (
    <div className="side-bar-arrangement">
      {/* 简化 */}
      {/* <div className="flex absolute right-[80px] top-20 z-10">
        <ShadTooltip content={t('flow.simplifyConfig')} side="bottom">
          <button className="extra-side-bar-buttons whitespace-pre bg-gray-0 rounded-l-full rounded-r-none" onClick={() => setOpen(true)}>
            <Combine strokeWidth={1.5} className="side-bar-button-size mr-2 pr-[2px]" color="#34d399"></Combine>{t('flow.simplify')}
          </button>
        </ShadTooltip>
        <ShadTooltip content={t('flow.notifications')} side="bottom">
          <button
            className="extra-side-bar-buttons whitespace-pre bg-gray-0 rounded-none"
            onClick={(event: React.MouseEvent<HTMLElement>) => {
              setNotificationCenter(false);
              const { top, left } = (event.target as Element).getBoundingClientRect();
              openPopUp(
                <>
                  <div className="absolute z-10" style={{ top: top + 40, left: left - AlertWidth }} ><AlertDropdown /></div>
                  <div className="header-notifications-box"></div>
                </>
              );
            }}
          >
            {notificationCenter && <div className="header-notifications"></div>}
            <Bell className="side-bar-button-size" aria-hidden="true" />{t('flow.notifications')}
          </button>
        </ShadTooltip>
        <ShadTooltip content={t('flow.exit')} side="bottom">
          <button className="extra-side-bar-buttons whitespace-pre bg-gray-0 rounded-r-full rounded-l-none" onClick={() => navgate('/build/skill/' + flow.id, { replace: true })} >
            <LogOut strokeWidth={1.5} className="side-bar-button-size mr-2 pr-[2px]" ></LogOut>{t('flow.exit')}
          </button>
        </ShadTooltip>
      </div> */}
      {/* 顶部按钮组 */}
      {/* <div className="side-bar-buttons-arrangement">
        <ShadTooltip content={t('flow.import')} side="bottom">
          <button className="extra-side-bar-buttons" onClick={() => { takeSnapshot(); uploadFlow() }} >
            <FileUp strokeWidth={1.5} className="side-bar-button-size " ></FileUp>
          </button>
        </ShadTooltip>
        <ShadTooltip content={t('flow.export')} side="bottom">
          <button className={classNames("extra-side-bar-buttons")} onClick={(event) => { openPopUp(<ExportModal />); }} >
            <FileDown strokeWidth={1.5} className="side-bar-button-size" ></FileDown>
          </button>
        </ShadTooltip>
        <ShadTooltip content={t('flow.code')} side="bottom">
          <button className={classNames("extra-side-bar-buttons")} onClick={(event) => { openPopUp(<ApiModal flow={flow} />); }} >
            <TerminalSquare strokeWidth={1.5} className="side-bar-button-size"></TerminalSquare>
          </button>
        </ShadTooltip>

        <ShadTooltip content={t('save')} side="bottom">
          <button className="extra-side-bar-buttons" onClick={(event) =>
            saveFlow(flow).then(_ =>
              _ && setSuccessData({ title: t('success') }))
          }
            disabled={!isPending}
          >
            <Save strokeWidth={1.5} className={"side-bar-button-size" + (isPending ? " " : " extra-side-bar-save-disable")} ></Save>
          </button>
        </ShadTooltip>
      </div> */}
      {/* <Separator /> */}
      <div className="side-bar-search-div-placement">
        <input type="text" name="search" id="search" placeholder={t('flow.searchComponent')} className="input-search rounded-full"
          onChange={(e) => {
            handleSearchInput(e.target.value);
            setSearch(e.target.value);
          }}
        />
        <div className="search-icon">
          {/* ! replace hash color here */}
          <Search size={20} strokeWidth={1.5} className="" />
        </div>
      </div>

      <div className="side-bar-components-div-arrangement">
        <PersonalComponents onDragStart={onDragStart}></PersonalComponents>
        {Object.keys(dataFilter)
          .sort()
          .map((d: keyof APIObjectType, i) =>
            Object.keys(dataFilter[d]).length > 0 ? (
              <TooltipProvider delayDuration={0} skipDelayDuration={200} key={i}>
                <Tooltip>
                  <TooltipTrigger>
                    <DisclosureComponent
                      openDisc={search.length == 0 ? false : true}
                      key={nodeNames[d]}
                      button={{
                        title: nodeNames[d] ?? nodeNames.unknown,
                        Icon: nodeIconsLucide[d] ?? nodeIconsLucide.unknown,
                        color: nodeColors[d] ?? nodeColors.unknown
                      }}
                    > </DisclosureComponent>
                  </TooltipTrigger>
                  <TooltipContent className="bg-gray-0 rounded-md max-h-[600px] overflow-y-auto no-scrollbar" side="right" collisionPadding={20}>
                    {Object.keys(dataFilter[d])
                      .sort()
                      .map((t: string, k) => (
                        d === 'input_output' && t === 'OutputNode' ? <></> :
                          <div key={data[d][t].display_name}>
                            <div key={k} data-tooltip-id={t}>
                              <div draggable
                                className="side-bar-components-border bg-background mt-1 rounded-full"
                                style={{ borderLeftColor: nodeColors[d] ?? nodeColors.unknown, }}
                                onDragStart={(event) =>
                                  onDragStart(event, { type: t, node: data[d][t], })
                                }
                                onDragEnd={() => {
                                  document.body.removeChild(
                                    document.getElementsByClassName(
                                      "cursor-grabbing"
                                    )[0]
                                  );
                                }}
                              >
                                <div className="side-bar-components-div-form border-solid rounded-full">
                                  <span className="side-bar-components-text"> {data[d][t].display_name} </span>
                                  <Menu className="side-bar-components-icon " />
                                </div>
                              </div>
                            </div>
                          </div>
                      ))}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            ) : (
              <div key={i}></div>
            )
          )}
      </div>
      {/* 高级配置l2配置 */}
      <L2ParamsModal data={flow} open={open} setOpen={setOpen} onSave={() => {
        saveFlow(flow);
        setSuccessData({ title: t('saved') });
      }}></L2ParamsModal>
    </div >
  );
}
