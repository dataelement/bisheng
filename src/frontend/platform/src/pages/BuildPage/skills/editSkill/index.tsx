import { TabsContext } from "@/contexts/tabsContext";
import { checkAppEditPermission, getFlowApi } from "@/controllers/API/flow";
import cloneDeep from "lodash-es/cloneDeep";
import { useContext, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import Page from "./PageComponent";

export default function FlowPage() {
  const { flow, setFlow } = useContext(TabsContext);
  const { id } = useParams();
  const [checking, setChecking] = useState(true)

  // const [flow, loadFlow] = useEditFlowStore(state => [state.flow, state.loadFlow]);
  // useEffect(() => {
  //   loadFlow(flowId)
  // }, [])
  const flowInit = async () => {
    await checkAppEditPermission(id, 1)
    getFlowApi(id).then(_flow => {
      setFlow('flow_init', _flow)
      setChecking(false)
    })
  }

  useEffect(() => {
    if (id && flow?.id !== id) {
      // 切换技能重新加载flow数据
      flowInit()
    } else {
      setChecking(false)
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

  if (checking) return null

  return (
    <div className="flow-page-positioning">
      {/* {flow && <Panne flow={flow} />} */}
      {copyFlow && <Page flow={copyFlow} preFlow={preFlow} />}
    </div>
  );
}
