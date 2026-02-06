import unittest

from docx.enum.text import WD_ALIGN_PARAGRAPH

from bisheng.workflow.nodes.report.docx_replace import DocxReplacer


class TestDocxReplacer(unittest.TestCase):
    def setUp(self):
        # need to prepare "test.png"、"test_chart1.png" in the same directory
        self.replacer = DocxReplacer("template.docx")

    def test_case(self):
        variables = {
            "var_1": [
                {"type": "text", "content": "这是正文 "},
                {"type": "text", "content": "这是粗体", "bold": True},
                {"type": "text", "content": " 继续正文"}
            ],
            "middle_placeholder": [
                {"type": "heading", "content": "数据表格", "level": 2},
                {
                    "type": "table",
                    "content": [
                        [
                            [
                                {"type": "text", "content": "列", "italic": True, "alignment": WD_ALIGN_PARAGRAPH.LEFT},
                                {"type": "text", "content": "1", "bold": True, "alignment": WD_ALIGN_PARAGRAPH.LEFT}
                            ],
                            {"type": "text", "content": "列2", "bold": True, "alignment": WD_ALIGN_PARAGRAPH.RIGHT}
                        ],
                        [
                            {"type": "text", "content": "数据1"},
                            {"type": "text", "content": "数据2"}
                        ]
                    ]
                }
            ],
            "report_date.123#1": [
                {"type": "text", "content": "2024-06-01"}
            ],
            "project_name": [
                {"type": "text", "content": "文档替换工具开发"}
            ],
            "executive_summary": [
                {"type": "text", "content": "本报告总结了文档替换工具的开发过程和使用方法。"},
                {"type": "image", "content": "test_chart1.png", "width": 5},
                {"type": "text", "content": "图表如上所示，展示了关键数据指标。"},
                {"type": "table", "content": [
                    [
                        {"type": "text", "content": "指标", "bold": True},
                        {"type": "text", "content": "数值", "bold": True},
                    ],
                    [
                        {"type": "text", "content": "指标A"},
                        {"type": "text", "content": "100"},
                    ], [
                        {"type": "text", "content": "指标B"},
                        {"type": "text", "content": "200"},
                    ],
                ]}
            ],
            "detailed_analysis": [
                {"type": "text", "content": "详细分析部分内容丰富，涵盖多个方面的数据解读。"},
                {"type": "heading", "content": "子标题：数据趋势", "level": 3},
                {"type": "text", "content": "通过对比历史数据，我们发现以下趋势..."}
            ],
            "chart_section": [
                {"type": "heading", "content": "红色图", "level": 3},
                {"type": "image", "content": "test.png"}
            ],
            "example_placeholder": [
                {"type": "text", "content": "这是一个示例占位符的替换内容。"}
            ],
            "table_title": [
                {"type": "text", "content": "以下是示例数据表格："}
            ],
            "table_date": [
                {"type": "text", "content": "2024-06-01"}
            ],
            "table_status": [
                {"type": "text", "content": "已完成"}
            ],
            "table_desc": [
                {"type": "text", "content": "这是表格的描述信息。"}
            ],
            "table_value": [
                {"type": "text", "content": "数值12345"}
            ],
            "table_summary": [
                {"type": "text", "content": "表格总结信息。"}
            ],
            "table_end": [
                {"type": "text", "content": "表格结束语。"}
            ],
            "only_placeholder": [
                {"type": "text", "content": "仅包含占位符的替换内容。"}
            ],
            "with_spaces": [
                {"type": "text", "content": "包含空格的    替换内容。"}
            ],
            "first": [
                {"type": "text", "content": "ONE"}
            ],
            "second": [
                {"type": "text", "content": "TWO"}
            ],
            "third": [
                {"type": "text", "content": "THREE"}
            ]
        }
        all_variables = self.replacer.extract_variables()
        print(all_variables)

        # 使用替换器
        self.replacer.replace_and_save(variables, "output.docx")
        print("文档替换完成！")


if __name__ == "__main__":
    unittest.main()
