import cloneDeep from "lodash-es/cloneDeep";
import { useContext, useEffect, useMemo } from "react";
import { useParams } from "react-router-dom";
import { TabsContext } from "@/contexts/tabsContext";
import { getFlowApi } from "@/controllers/API/flow";
import Page from "./PageComponent";

export default function FlowPage() {
  const { flow, setFlow } = useContext(TabsContext);
  const { id } = useParams();
  // const [flow, loadFlow] = useEditFlowStore(state => [state.flow, state.loadFlow]);
  // useEffect(() => {
  //   loadFlow(flowId)
  // }, [])
  useEffect(() => {
    if (id && flow?.id !== id) {
      // 切换技能重新加载flow数据
      getFlowApi(id).then(_flow => setFlow('flow_init', _flow))
    }

    // return () => setFlow('destroy', null)
  }, [])

  const [copyFlow, preFlow] = useMemo(() => {
    if (flow?.id === id) {
      const copyFlow = cloneDeep(flow)
      return [copyFlow, JSON.stringify(copyFlow?.data || null)] as const
    }
    return []
  }, [flow, id])


  return (
    <div className="flow-page-positioning">
      {/* {flow && <Panne flow={flow} />} */}
      {copyFlow && <Page flow={copyFlow} preFlow={preFlow} />}
    </div>
  );
}
