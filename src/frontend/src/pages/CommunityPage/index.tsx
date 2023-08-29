import { GitFork, Users2 } from "lucide-react";
import { useContext, useEffect, useState } from "react";
import { Button } from "../../components/ui/button";
import { alertContext } from "../../contexts/alertContext";
import { TabsContext } from "../../contexts/tabsContext";

import { useNavigate } from "react-router-dom";
import { CardComponent } from "../../components/cardComponent";
import { getExamples } from "../../controllers/API";
import { FlowType } from "../../types/flow";
export default function CommunityPage() {
  const { flows, setTabId, downloadFlows, uploadFlows, addFlow } =
    useContext(TabsContext);
  useEffect(() => {
    setTabId("");
  }, []);
  const { setErrorData } = useContext(alertContext);
  const [loadingExamples, setLoadingExamples] = useState(false);
  const [examples, setExamples] = useState<FlowType[]>([]);
  function handleExamples() {
    setLoadingExamples(true);
    getExamples()
      .then((result) => {
        setLoadingExamples(false);
        setExamples(result);
      })
      .catch((error) =>
        setErrorData({
          title: "加载示例时出现错误，请重试",
          list: [error.message],
        })
      );
  }
  const navigate = useNavigate();

  useEffect(() => {
    handleExamples();
  }, []);
  return (
    <div className="community-page-arrangement">
      <div className="community-page-nav-arrangement">
        <span className="community-page-nav-title">
          <Users2 className="w-6" />
          Community Examples
        </span>
      </div>
      <div className="community-pages-flows-panel">
        {!loadingExamples &&
          examples.map((flow, idx) => (
            <CardComponent
              key={idx}
              flow={flow}
              id={flow.id}
              button={
                <Button
                  variant="outline"
                  size="sm"
                  className="whitespace-nowrap "
                  onClick={() => {
                    addFlow(flow, true).then((id) => {
                      navigate("/flow/" + id);
                    });
                  }}
                >
                  <GitFork className="main-page-nav-button" />
                  Fork Example
                </Button>
              }
            />
          ))}
      </div>
    </div>
  );
}
