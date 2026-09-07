import { describe, expect, it } from "vitest"
import i18next from "i18next"
import { getMetricDisplayName } from "../pages/Dashboard/components/config/DatasetSelector"
import zhDashboard from "../../public/locales/zh-Hans/dashboard.json"
import enDashboard from "../../public/locales/en-US/dashboard.json"
import jaDashboard from "../../public/locales/ja/dashboard.json"

describe("dataset metric isolation and naming", () => {
  const createTranslator = (resources: any) => {
    const instance = i18next.createInstance()
    instance.init({
      lng: "test",
      resources: {
        test: {
          dashboard: resources,
        },
      },
      defaultNS: "dashboard",
    })
    return (keys: string | string[], options?: { defaultValue?: string }) => {
      return instance.t(keys, options)
    }
  }

  it("resolves total_qa_count to '总问答数' for mid_realtime_qa_question_fact and '总QA对数' for mid_knowledge_file_increment in zh-Hans", () => {
    const tZh = createTranslator(zhDashboard)

    const realtimeMetric = {
      field: "total_qa_count",
      name: "问答总数",
      field_type: "number",
    }
    const knowledgeMetric = {
      field: "total_qa_count",
      name: "总QA对数",
      field_type: "number",
    }

    const realtimeName = getMetricDisplayName(tZh, "mid_realtime_qa_question_fact", realtimeMetric)
    const knowledgeName = getMetricDisplayName(tZh, "mid_knowledge_file_increment", knowledgeMetric)

    expect(realtimeName).toBe("总问答数")
    expect(knowledgeName).toBe("总QA对数")
  })

  it("resolves total_qa_count to 'Total Q&As' for realtime QA and 'Total QA Pairs' for knowledge file in en-US", () => {
    const tEn = createTranslator(enDashboard)

    const realtimeMetric = {
      field: "total_qa_count",
      name: "Total Q&As",
      field_type: "number",
    }
    const knowledgeMetric = {
      field: "total_qa_count",
      name: "Total QA Pairs",
      field_type: "number",
    }

    const realtimeName = getMetricDisplayName(tEn, "mid_realtime_qa_question_fact", realtimeMetric)
    const knowledgeName = getMetricDisplayName(tEn, "mid_knowledge_file_increment", knowledgeMetric)

    expect(realtimeName).toBe("Total Q&As")
    expect(knowledgeName).toBe("Total QA Pairs")
  })

  it("resolves total_qa_count to '総Q&A数' for realtime QA and '総Q&Aペア数' for knowledge file in ja", () => {
    const tJa = createTranslator(jaDashboard)

    const realtimeMetric = {
      field: "total_qa_count",
      name: "総Q&A数",
      field_type: "number",
    }
    const knowledgeMetric = {
      field: "total_qa_count",
      name: "総Q&Aペア数",
      field_type: "number",
    }

    const realtimeName = getMetricDisplayName(tJa, "mid_realtime_qa_question_fact", realtimeMetric)
    const knowledgeName = getMetricDisplayName(tJa, "mid_knowledge_file_increment", knowledgeMetric)

    expect(realtimeName).toBe("総Q&A数")
    expect(knowledgeName).toBe("総Q&Aペア数")
  })

  it("falls back to metric.name when neither specific nor general translation exists", () => {
    const tEmpty = createTranslator({})
    const customMetric = {
      field: "custom_untranslated_metric",
      name: "自定义指标",
      field_type: "number",
    }

    const metricName = getMetricDisplayName(tEmpty, "mid_realtime_qa_question_fact", customMetric)
    expect(metricName).toBe("自定义指标")
  })
})
