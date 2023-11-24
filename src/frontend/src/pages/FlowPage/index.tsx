import { useContext, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { TabsContext } from "../../contexts/tabsContext";
import { getVersion } from "../../controllers/API";
import Page from "./components/PageComponent";
import _ from "lodash";

export default function FlowPage() {
  const { flows, setTabId } = useContext(TabsContext);
  const { id } = useParams();
  useEffect(() => {
    setTabId(id);
  }, [id]);

  // Initialize state variable for the version
  // const [version, setVersion] = useState("");
  // useEffect(() => {
  //   getVersion().then((data) => {
  //     setVersion(data.version);
  //   });
  // }, []);
  const flow = useMemo(() => {
    const _flow = flows.find((flow) => flow.id === id)
    const copyFlow = _flow && _.cloneDeep(_flow)
    return [copyFlow, JSON.stringify(copyFlow?.data || null)] as const
  }, [flows, id])


  return (
    <div className="flow-page-positioning">
      {flow[0] && <Page flow={flow[0]} preFlow={flow[1]} />}
      {/* <a
        target={"_blank"}
        href="https://logspace.ai/"
        className="logspace-page-icon"
      >
        {version && <div className="mt-1">⛓️ Langflow v{version}</div>}
        <div className={version ? "mt-2" : "mt-1"}>Created by Logspace</div>
      </a> */}
    </div>
  );
}
