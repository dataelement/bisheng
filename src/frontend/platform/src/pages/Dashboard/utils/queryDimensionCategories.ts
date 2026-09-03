// Customer feedback (2026-09-01): the 查询组件 (Query component) must support choosing
// query conditions from a fixed set of categories — 知识库大类/知识分类/组织架构/业务域,
// alongside the time picker it already has — instead of only ever querying by time.
// This module is the single source of truth for "which category does this dataset field
// belong to", shared by the Query component's configurator (ChartSelector.tsx, to build the
// selectable field list) and, if needed elsewhere, anything that needs the same grouping.
import { orgLevelForField } from "./groupCrossTabRows"

export type QueryDimensionCategory = "space_level" | "file_category" | "business_domain" | "org_hierarchy"

export const QUERY_DIMENSION_CATEGORY_LABELS: Record<QueryDimensionCategory, string> = {
  space_level: "知识库大类",
  file_category: "知识分类",
  business_domain: "业务域",
  org_hierarchy: "组织架构",
}

// Non-org categories key off the exact ETL "_name" field (the literal display-text
// snapshot), matching the "_code" sibling's paired "_name" field convention already used
// throughout init_dataset.py (see DimensionFilterConfigurator's own _id/_code -> _name
// pairing logic).
const NON_ORG_CATEGORY_BY_FIELD: Record<string, QueryDimensionCategory> = {
  space_level_name: "space_level",
  file_category_name: "file_category",
  file_subcategory_name: "file_category",
  business_domain_name: "business_domain",
}

export function queryDimensionCategoryForField(fieldId: string): QueryDimensionCategory | null {
  if (NON_ORG_CATEGORY_BY_FIELD[fieldId]) return NON_ORG_CATEGORY_BY_FIELD[fieldId]
  return orgLevelForField(fieldId) ? "org_hierarchy" : null
}
