# Refresh belonging_organization_id for the 246 department-library files in 纠错3.xlsx.
# ruff: noqa: RUF001
# Preview is the default. --apply writes MySQL, preserves update_time, then queues content-stat.
# Run from src/backend, or from /app inside the backend container:
#   python scripts/backfill_correction3_belonging.py
#   python scripts/backfill_correction3_belonging.py --apply

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

_BACKEND_ROOT = str(Path(__file__).resolve().parents[1])
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

TENANT_ID = 1
ROWS = [
    {"file_id": 110466, "user_id": 13154, "file_name": "提高热镀锌高铝高强钢产品合格率-4.pptx"},
    {"file_id": 110774, "user_id": 18513, "file_name": "球团一系列环保低碳示范产线改造（结题答辩）.pptx"},
    {"file_id": 110775, "user_id": 17974, "file_name": "提高冷硬卷头尾厚度控制精度-DMAIC12.12.pptx"},
    {"file_id": 110779, "user_id": 12675, "file_name": "BB+余晓波+3#高炉炉缸浇注修复效能提升（20221220最终版）.ppt"},
    {
        "file_id": 110912,
        "user_id": 12390,
        "file_name": "2021-03-10-合理化提案表-迁钢二热轧-提升节奏后数据池存储错位导致的严重厚超问题解决.doc",
    },
    {
        "file_id": 111037,
        "user_id": 12390,
        "file_name": "2020年07月27日：合理化-提案表--迁钢二热轧二级控制系统-HMI画面版本兼容性测试及优化.doc",
    },
    {"file_id": 112952, "user_id": 18513, "file_name": "20240709带焙产线配加镁粉工业试验总结.doc"},
    {"file_id": 89942, "user_id": 4155, "file_name": "能源部供水作业区泵站操作工岗位作业规程2026最新版.pdf"},
    {"file_id": 89944, "user_id": 4155, "file_name": "Z-GTQGNY-019-自动化点检岗位作业规程(2025印刷版).pdf"},
    {
        "file_id": 89945,
        "user_id": 4155,
        "file_name": "Z-GTQGNY-020能源部设备管理室电气点检岗位作业规程（2025印刷版）.pdf",
    },
    {"file_id": 89946, "user_id": 4155, "file_name": "Z-GTQGNY-043能源部油品检验岗位作业规程（2025印刷版）.pdf"},
    {"file_id": 89947, "user_id": 4155, "file_name": "Z-GTQGNY-045能源部设备管理室库工岗位作业规程（2025印刷版）.pdf"},
    {"file_id": 89948, "user_id": 4155, "file_name": "Z-GTQGNY-046能源部设备管理室油品净化岗位规程（2025印刷版）.pdf"},
    {"file_id": 89950, "user_id": 4155, "file_name": "Z-GTQGNY-021-能源部燃气作业区柜区加压站岗位作业规程.pdf"},
    {"file_id": 89951, "user_id": 4155, "file_name": "Z-GTQGNY-022-能源部燃气作业区点检岗位作业规程.pdf"},
    {"file_id": 89952, "user_id": 4155, "file_name": "Z-GTQGNY-023-能源部燃气作业区焦炉加压站岗位作业规程.pdf"},
    {"file_id": 89953, "user_id": 4155, "file_name": "Z-GTQGNY-024-能源部燃气作业区作业长岗位作业规程.pdf"},
    {"file_id": 89956, "user_id": 4155, "file_name": "能源部标识工作室岗位作业规程.pdf"},
    {"file_id": 89957, "user_id": 4155, "file_name": "能源部水处理作业区1#水处理站岗位作业规程.pdf"},
    {"file_id": 89958, "user_id": 4155, "file_name": "能源部水处理作业区2#水处理站岗位作业规程.pdf"},
    {"file_id": 89959, "user_id": 4155, "file_name": "能源部水处理作业区3#除盐站岗位作业规程.pdf"},
    {"file_id": 89960, "user_id": 4155, "file_name": "能源部水处理作业区点检岗位作业规程.pdf"},
    {"file_id": 89961, "user_id": 4155, "file_name": "能源部水处理作业区管道运行岗位作业规程.pdf"},
    {"file_id": 89962, "user_id": 4155, "file_name": "1、100MW亚临界机组汽机岗位作业规程（试运行版）.doc"},
    {"file_id": 89963, "user_id": 4155, "file_name": "2、100MW亚临界机组锅炉岗位作业规程（试运行版）.doc"},
    {
        "file_id": 89964,
        "user_id": 4155,
        "file_name": "Z-GTQGNY-031----2024.9修订--发电作业区--循环发电汽机岗位作业规程.pdf",
    },
    {
        "file_id": 89965,
        "user_id": 4155,
        "file_name": "Z-GTQGNY-032----2024.9修订--发电作业区--循环发电作业长岗位作业规程.pdf",
    },
    {
        "file_id": 89966,
        "user_id": 4155,
        "file_name": "Z-GTQGNY-033----2024.9修订--发电作业区--热电汽机岗位作业规程.pdf",
    },
    {
        "file_id": 89967,
        "user_id": 4155,
        "file_name": "Z-GTQGNY-034----2024.9修订--发电作业区--热电锅炉岗位作业规程.pdf",
    },
    {
        "file_id": 89969,
        "user_id": 4155,
        "file_name": "Z-GTQGNY-044----2024.9修订--发电作业区--发电作业区机械点检岗位作业规程.pdf",
    },
    {
        "file_id": 89970,
        "user_id": 4155,
        "file_name": "Z-GTQGNY-045----2024.9修订--发电作业区--化学水运行岗位作业规程.pdf",
    },
    {
        "file_id": 89971,
        "user_id": 4155,
        "file_name": "Z-GTQGNY-049----2024.9修订--发电作业区--发电作业区电气点检岗位作业规程.pdf",
    },
    {"file_id": 89974, "user_id": 4155, "file_name": "能源部压差发电作业区点检岗位作业规程（打印版20250207）.pdf"},
    {
        "file_id": 89975,
        "user_id": 4155,
        "file_name": "能源部压差发电作业区煤气干法除尘岗位作业规程（打印版20250207）.pdf",
    },
    {"file_id": 89976, "user_id": 4155, "file_name": "1能源制氧点检岗位规程20240730制氧作业长250313.pdf"},
    {
        "file_id": 89977,
        "user_id": 4155,
        "file_name": "1能源部制氧化验岗位作业规程20240910交接班1224制氧作业长250313.pdf",
    },
    {"file_id": 89978, "user_id": 4155, "file_name": "（1终版）能源部制氧作业长岗位作业规程20250313（新增）.pdf"},
    {
        "file_id": 89979,
        "user_id": 4155,
        "file_name": "（1终版）能源部制氧空分岗位作业规程20250313（空分和配电合并）.pdf",
    },
    {"file_id": 89980, "user_id": 4155, "file_name": "供电作业区 电气点检岗位作业规程（2024.5.24修改）.pdf"},
    {"file_id": 89982, "user_id": 4155, "file_name": "新版规程-供电作业区（2025年1月份修改）.pdf"},
    {"file_id": 89983, "user_id": 4155, "file_name": "2025版规程-能源部供风作业区点检岗位规程（打印版）.pdf"},
    {"file_id": 89984, "user_id": 4155, "file_name": "2025版规程-能源部供风作业区空压机岗位作业规程（打印版）.pdf"},
    {
        "file_id": 89985,
        "user_id": 4155,
        "file_name": "2025版规程-能源部供风作业区高炉鼓风机作业长岗位作业规程（打印版）.pdf",
    },
    {"file_id": 89986, "user_id": 4155, "file_name": "2025版规程-能源部供风作业区高炉鼓风机岗位作业规程(打印版).pdf"},
    {"file_id": 115412, "user_id": 18513, "file_name": "烧结二烧耐热风机制约烧结机效率发挥原因探究.doc"},
    {"file_id": 118863, "user_id": 18513, "file_name": "20240708配矿软件需求.xlsx"},
    {"file_id": 93286, "user_id": 11534, "file_name": "1发现JMP.pdf"},
    {"file_id": 93287, "user_id": 11534, "file_name": "2使用JMP.pdf"},
    {"file_id": 93288, "user_id": 11534, "file_name": "3基本分析.pdf"},
    {"file_id": 93289, "user_id": 11534, "file_name": "4基本绘图.pdf"},
    {"file_id": 93290, "user_id": 11534, "file_name": "5刻画器指南.pdf"},
    {"file_id": 93291, "user_id": 11534, "file_name": "6实验设计指南.pdf"},
    {"file_id": 93292, "user_id": 11534, "file_name": "7拟合线性模型.pdf"},
    {"file_id": 93293, "user_id": 11534, "file_name": "8预测和专业建模.pdf"},
    {"file_id": 93294, "user_id": 11534, "file_name": "9多元方法.pdf"},
    {"file_id": 93295, "user_id": 11534, "file_name": "10质量和过程方法.pdf"},
    {"file_id": 93296, "user_id": 11534, "file_name": "11可靠性和生存方法.pdf"},
    {"file_id": 93297, "user_id": 11534, "file_name": "12消费者研究.pdf"},
    {"file_id": 93298, "user_id": 11534, "file_name": "13菜单卡.pdf"},
    {"file_id": 93299, "user_id": 11534, "file_name": "14快速参考.pdf"},
    {"file_id": 93300, "user_id": 11534, "file_name": "discovering-jmp-zh.pdf"},
    {"file_id": 93301, "user_id": 11534, "file_name": "DOE试验设计(SAS_JMP)经典学习案例.pdf"},
    {"file_id": 93409, "user_id": 11534, "file_name": "信息安全体系管理手册v2.1(1).pdf"},
    {"file_id": 93410, "user_id": 11534, "file_name": "中华人民共和国个人信息保护法.pdf"},
    {"file_id": 93411, "user_id": 11534, "file_name": "中华人民共和国国家安全法.pdf"},
    {"file_id": 93412, "user_id": 11534, "file_name": "中华人民共和国数据安全法.pdf"},
    {"file_id": 93413, "user_id": 11534, "file_name": "中华人民共和国网络安全法.pdf"},
    {"file_id": 93414, "user_id": 11534, "file_name": "中华人民共和国著作权法__中国政府网.pdf"},
    {"file_id": 93415, "user_id": 11534, "file_name": "中华人民共和国计算机信息系统安全保护条例.pdf"},
    {"file_id": 93416, "user_id": 11534, "file_name": "中华人民共和国计算机信息网络国际联网管理暂行规定.pdf"},
    {"file_id": 93417, "user_id": 11534, "file_name": "中国互联网络域名管理办法.docx"},
    {"file_id": 93418, "user_id": 11534, "file_name": "互联网信息服务管理办法.pdf"},
    {"file_id": 93419, "user_id": 11534, "file_name": "互联网安全保护技术措施规定.docx"},
    {"file_id": 93420, "user_id": 11534, "file_name": "信息安全等级保护管理办法1.0-2007.pdf"},
    {"file_id": 93421, "user_id": 11534, "file_name": "商用密码管理条例.docx"},
    {"file_id": 93422, "user_id": 11534, "file_name": "GB50174-2017：数据中心设计规范.pdf"},
    {"file_id": 93424, "user_id": 11534, "file_name": "网络数据安全管理条例_20240924.pdf"},
    {"file_id": 93425, "user_id": 11534, "file_name": "计算机信息网络国际联网安全保护管理办法.pdf"},
    {"file_id": 93426, "user_id": 11534, "file_name": "计算机病毒防治管理办法.docx"},
    {"file_id": 93427, "user_id": 11534, "file_name": "计算机软件保护条例.pdf"},
    {"file_id": 93428, "user_id": 11534, "file_name": "非经营性互联网信息服务备案管理办法.docx"},
    {"file_id": 93429, "user_id": 11534, "file_name": "GB 17859-1999 计算机信息系统 安全保护等级划分准则.pdf"},
    {"file_id": 93430, "user_id": 11534, "file_name": "GBT 20984-2022 信息安全技术 信息安全风险评估方法.pdf"},
    {
        "file_id": 93431,
        "user_id": 11534,
        "file_name": "GBT 20985.1-2017 信息技术 安全技术 信息安全事件管理 第1部分：事件管理原理.pdf",
    },
    {
        "file_id": 93432,
        "user_id": 11534,
        "file_name": "GBT 20985.2-2020 信息技术 安全技术 信息安全事件管理 第2部分 事件响应规划和准备指南.pdf",
    },
    {"file_id": 93433, "user_id": 11534, "file_name": "GBT 20986-2023 信息安全技术 网络安全事件分类分级指南.pdf"},
    {"file_id": 93434, "user_id": 11534, "file_name": "GBT 22080-2016 信息技术 安全技术 信息安全管理体系 要求.pdf"},
    {"file_id": 93435, "user_id": 11534, "file_name": "GBT 22080-2025《网络安全技术 信息安全管理体系 要求》.pdf"},
    {"file_id": 93436, "user_id": 11534, "file_name": "GBT 22081-2016 信息技术 安全技术 信息安全控制实践指南.pdf"},
    {"file_id": 93437, "user_id": 11534, "file_name": "GBT 24363-2009 信息安全技术信息安全应急响应计划规范.pdf"},
    {"file_id": 93438, "user_id": 11534, "file_name": "GBT 24364-2023 信息安全技术 信息安全风险管理实施指南.pdf"},
    {
        "file_id": 93439,
        "user_id": 11534,
        "file_name": "GBT 29246-2017 信息技术 安全技术 信息安全管理体系 概述和词汇.pdf",
    },
    {"file_id": 93440, "user_id": 11534, "file_name": "GBT 31496-2023 信息技术 安全技术 信息安全管理体系 指南.pdf"},
    {"file_id": 93441, "user_id": 11534, "file_name": "GBT 31509 -2015 信息安全技术 信息安全风险评估实施指南.pdf"},
    {"file_id": 93442, "user_id": 11534, "file_name": "GBT 31722-2015 信息技术 安全技术 信息安全风险管理.pdf"},
    {"file_id": 93443, "user_id": 11534, "file_name": "GBT 33132-2016 信息安全技术 信息安全风险处理实施指南.pdf"},
    {"file_id": 93445, "user_id": 11534, "file_name": "智能制造能力成熟度评估方法GBT39117-2020(1).pdf"},
    {
        "file_id": 93446,
        "user_id": 11534,
        "file_name": "GB_T 31722-2025 信息安全技术 信息安全风险管理指导（正式高清版）.pdf",
    },
    {"file_id": 93447, "user_id": 11534, "file_name": "GB∕T 22239-2019 信息安全技术 网络安全等级保护基本要求-2.0.pdf"},
    {"file_id": 93448, "user_id": 11534, "file_name": "GB∕T 22240-2020 信息安全技术 网络安全等级保护定级指南.pdf"},
    {"file_id": 93449, "user_id": 11534, "file_name": "GB∕T 25058-2019 信息安全技术 网络安全等级保护实施指南.pdf"},
    {
        "file_id": 93450,
        "user_id": 11534,
        "file_name": "GB∕T 25070-2019 信息安全技术 网络安全等级保护安全设计技术要求.pdf",
    },
    {"file_id": 93451, "user_id": 11534, "file_name": "GB∕T 28448-2019 信息安全技术 网络安全等级保护测评要求.pdf"},
    {"file_id": 93452, "user_id": 11534, "file_name": "GB∕T 28449-2018 信息安全技术 网络安全等级保护测评过程指南.pdf"},
    {"file_id": 93453, "user_id": 11534, "file_name": "GB∕T 31496-2015 信息技术 安全技术 信息安全管理体系实施指南.pdf"},
    {"file_id": 93454, "user_id": 11534, "file_name": "GB∕T 39116-2020 智能制造能力成熟度模型.pdf"},
    {
        "file_id": 93455,
        "user_id": 11534,
        "file_name": "ISO∕IEC 27001 ：2022信息安全、网络安全和隐私保护（CCSC内部翻译版）.pdf",
    },
    {"file_id": 93456, "user_id": 11534, "file_name": "YDT 4981—2024工业领域重要数据识别指南.docx"},
    {"file_id": 93457, "user_id": 11534, "file_name": "YDT 4982—2024工业企业数据安全防护要求.docx"},
    {"file_id": 93458, "user_id": 11534, "file_name": "YDT-6415-2025工业领域数据安全风险评估规范.docx"},
    {"file_id": 93459, "user_id": 11534, "file_name": "国家人工智能产业综合标准化体系建设指南（2024版）.pdf"},
    {"file_id": 93460, "user_id": 11534, "file_name": "网络安全等级保护条例  征求意见稿.pdf"},
    {"file_id": 93462, "user_id": 11534, "file_name": "信息技术服务数字化转型的成熟度模型GBT+43439-2023.pdf"},
    {
        "file_id": 103351,
        "user_id": 12620,
        "file_name": "0150-2025石油天然气输送管用热轧宽钢带产品质量分级和评价方法.pdf",
    },
    {
        "file_id": 103352,
        "user_id": 12620,
        "file_name": "T-CISA 235-2022《钢板和钢带全板厚度精度评价指标及计算方法》.pdf",
    },
    {
        "file_id": 103353,
        "user_id": 12620,
        "file_name": "TCISA 057-2020 TCSTE 0059-2020“领跑者”标准评价要求  全工艺冷轧取向电工钢.pdf",
    },
    {"file_id": 103354, "user_id": 12620, "file_name": "铁矿球团带式焙烧机工艺技术规范.PDF"},
    {"file_id": 103355, "user_id": 12620, "file_name": "转炉烟气排放高精度过滤技术规范_00015502429820101.pdf"},
    {"file_id": 103356, "user_id": 12620, "file_name": "团体标准：铁矿球团带式焙烧机工艺技术规范T CIET 1661-2025.PDF"},
    {
        "file_id": 103357,
        "user_id": 12620,
        "file_name": "0373-2024绿色设计产品评价技术规范碳素结构钢和低合金结构钢热轧钢板及钢带.pdf",
    },
    {"file_id": 103358, "user_id": 12620, "file_name": "0463-2024汽车用高强度热轧复相钢板及钢带.pdf"},
    {"file_id": 103359, "user_id": 12620, "file_name": "0464-2024汽车用高扩孔钢热轧钢板及钢带.pdf"},
    {"file_id": 103360, "user_id": 12620, "file_name": "0465-2024连续油管用钢带.pdf"},
    {
        "file_id": 103361,
        "user_id": 12620,
        "file_name": "TCSTM 01297—2025《绿色低碳技术评价规范  转炉提升废钢比技术》.pdf",
    },
    {
        "file_id": 103362,
        "user_id": 12620,
        "file_name": "TCSTM 01298—2025《绿色低碳技术评价规范  烧结烟气内循环技术》.pdf",
    },
    {"file_id": 103363, "user_id": 12620, "file_name": "T_SSEA 0223-2024 氢气输送管线用热轧宽钢带.pdf"},
    {
        "file_id": 103364,
        "user_id": 12620,
        "file_name": "T_SSEA 0373-2024 T_CSTA 0085-2024绿色设计产品评价技术规范 碳素结构钢和低合金结构钢热轧钢板及钢带.pdf",
    },
    {"file_id": 103365, "user_id": 12620, "file_name": "绿色生产管理评价标准(第2部分-焦化）.pdf"},
    {"file_id": 103366, "user_id": 12620, "file_name": "绿色生产管理评价标准(第6部分-热轧）.pdf"},
    {"file_id": 103367, "user_id": 12620, "file_name": "绿色生产管理评价标准(第7部分-冷轧（碳钢）.pdf"},
    {"file_id": 103368, "user_id": 12620, "file_name": "绿色生产管理评价标准(第8部分-冷轧（电工钢）.pdf"},
    {"file_id": 103369, "user_id": 12620, "file_name": "绿色生产管理评价标准（第1部分-通则).pdf"},
    {"file_id": 103370, "user_id": 12620, "file_name": "绿色生产管理评价标准（第3部分-烧结球团）.pdf"},
    {"file_id": 103371, "user_id": 12620, "file_name": "绿色生产管理评价标准（第5部分-转炉炼钢）.pdf"},
    {"file_id": 103372, "user_id": 12620, "file_name": "AQ 2025-2025 烧结球团安全规范.pdf"},
    {
        "file_id": 103373,
        "user_id": 12620,
        "file_name": "YBT 4769-2019绿色设计产品评价技术规范  新能源汽车用无取向电工钢.pdf",
    },
    {
        "file_id": 103374,
        "user_id": 12620,
        "file_name": "RBT+235—2024+质量管理体系分级认证　要求和评价准则+钢铁行业.pdf",
    },
    {"file_id": 103375, "user_id": 12620, "file_name": "YBT 6118-2023 钢铁行业节能诊断技术导则.pdf"},
    {"file_id": 103376, "user_id": 12620, "file_name": "YB-T 6309-2024 钢铁生产工序能源管理技术规范1.pdf"},
    {"file_id": 103377, "user_id": 12620, "file_name": "YBT 6233 2024取水定额+钢铁行业热轧.pdf"},
    {"file_id": 103378, "user_id": 12620, "file_name": "YBT 6100-2023 高炉铁水罐加盖保温技术规范 .pdf"},
    {"file_id": 103379, "user_id": 12620, "file_name": "YBT4883-2020 钢铁企业水平平衡测试与计算方法.pdf"},
    {"file_id": 103380, "user_id": 12620, "file_name": "YBT 6212-2024钢铁企业碳减排成本计算方法.pdf"},
    {"file_id": 103381, "user_id": 12620, "file_name": "YB_T 6102-2023《高炉炉顶均压煤气及休风煤气回收技术要求》.pdf"},
    {
        "file_id": 103382,
        "user_id": 12620,
        "file_name": "YB T 4739-2019铬铁 磷、铝、钛、铜、锰、钙含量的测定 电感耦合等离子体原子发射光谱法.pdf",
    },
    {"file_id": 103383, "user_id": 12620, "file_name": "YB-T 6286-2024 热轧钢板及钢带工程同板差检测方法.pdf"},
    {
        "file_id": 103384,
        "user_id": 12620,
        "file_name": "YBT 4174.2-2023硅钙合金分析方法 第2部分：磷含量的测定 电感耦合等离子体原子发射光谱法.pdf",
    },
    {"file_id": 103385, "user_id": 12620, "file_name": "YBT 4843-2020 工频用冷轧取向电工钢薄带（片）.pdf"},
    {"file_id": 103386, "user_id": 12620, "file_name": "YBT 4841 石油天然气输送管用抗酸性热轧宽钢带.pdf"},
    {"file_id": 103387, "user_id": 12620, "file_name": "YBT6328-2024冶金工业建构筑物安全运维技术规范-设备部.pdf"},
    {"file_id": 103388, "user_id": 12620, "file_name": "YBT 6140-2023冶金用消石灰行业标准.pdf"},
    {"file_id": 103389, "user_id": 12620, "file_name": "YBT 6333-2024温室气体排放核算与报告要求粗钢生产主要工序.pdf"},
    {"file_id": 103390, "user_id": 12620, "file_name": "YB_T 4003-2016 连铸钢板坯低倍组织缺陷评级图.pdf"},
    {"file_id": 103391, "user_id": 12620, "file_name": "GBT+28294-2024+钢铁渣复合料.pdf"},
    {"file_id": 103392, "user_id": 12620, "file_name": "GBT+13305-2024不锈钢中α-相含量测定法.pdf"},
    {"file_id": 103393, "user_id": 12620, "file_name": "GB T 30898-2025炼钢用渣钢.pdf"},
    {"file_id": 103406, "user_id": 12620, "file_name": "GBT+45459-2025.pdf"},
    {
        "file_id": 103407,
        "user_id": 12620,
        "file_name": "GBT 20887.3-2022 汽车用高强度热连轧钢板及钢带  第3部分：双相钢.PDF",
    },
    {"file_id": 103408, "user_id": 12620, "file_name": "GB T 32965-2025 钢渣加工和金属回收技术规范.pdf"},
    {
        "file_id": 103409,
        "user_id": 12620,
        "file_name": "GBT+44391-2024用单片测试仪和光学传感器测量晶粒取向电工钢带(片)磁致伸缩特性的方法.pdf",
    },
    {"file_id": 103410, "user_id": 13742, "file_name": "【疑似夹杂开裂异议反查报告】-SA6左前轮罩-首钢.pdf"},
    {"file_id": 103411, "user_id": 13742, "file_name": "佛山大众CR210BH入厂检BH值不合分析.pdf"},
    {
        "file_id": 103412,
        "user_id": 13742,
        "file_name": "鄂尔多斯奇瑞瑞虎后背门内板批量开裂质量异议分析与整改报告-奇瑞.pdf",
    },
    {"file_id": 103413, "user_id": 13742, "file_name": "抚州比亚迪EWEA顶盖外板开裂分析报告.pdf"},
    {"file_id": 103414, "user_id": 13742, "file_name": "光束汽车J05车型左右后门外板锌渣质量异议分析报告-光束.pdf"},
    {"file_id": 103415, "user_id": 13742, "file_name": "关于河北长安汽车P201后门内板开裂问题的分析报告.pdf"},
    {"file_id": 103416, "user_id": 13742, "file_name": "光束J01前门内板拼焊料色差问题分析报告 - 光束.pdf"},
    {"file_id": 103417, "user_id": 13742, "file_name": "光束汽车J05左后轮罩内板开裂分析与整改报告--光束.pdf"},
    {"file_id": 103476, "user_id": 13742, "file_name": "平湖长城A02机盖外板夹杂质量异议分析与整改报告—长城.pdf"},
    {"file_id": 103477, "user_id": 13742, "file_name": "天津大众VW326探岳后门内板开裂反查分析报告.pdf"},
    {
        "file_id": 103478,
        "user_id": 13742,
        "file_name": "西安比亚迪冲压工厂SGH左上封板零件材料偶发疑似腐蚀性黑斑问题分析.pdf",
    },
    {"file_id": 103479, "user_id": 13742, "file_name": "一汽大众AU401车型集采外制件CR300LA表面沉没辊印缺陷分析.pdf"},
    {"file_id": 103480, "user_id": 13742, "file_name": "一汽大众VW491车型集采外制件HX340LAD+Z表面锈斑缺陷分析.pdf"},
    {"file_id": 103481, "user_id": 13742, "file_name": "一汽大众集采CR240LA冲压橘皮分析.pdf"},
    {"file_id": 103482, "user_id": 13742, "file_name": "一汽解放St13混卷分析.pdf"},
    {"file_id": 103483, "user_id": 13742, "file_name": "长春大众CCFB侧围内板切边不良分析.pdf"},
    {"file_id": 103484, "user_id": 13742, "file_name": "一汽大众VW326探岳前地板冲压开裂分析报告.pdf"},
    {
        "file_id": 103485,
        "user_id": 13742,
        "file_name": "长城泰州ES11发动机罩外板高点（疑似材料脱锌）质量异议分析—长城.pdf",
    },
    {"file_id": 103486, "user_id": 13742, "file_name": "长春大众揽巡发罩外板亮点缺陷分析.pdf"},
    {"file_id": 103487, "user_id": 13742, "file_name": "长春大众CCFB前门内板CR4冲压缩孔分析-20250214.pdf"},
    {"file_id": 103488, "user_id": 13742, "file_name": "郑州比亚迪P5左前轮罩后段开裂分析报告.pdf"},
    {
        "file_id": 103489,
        "user_id": 13742,
        "file_name": "重庆长城P3011镀锌板DC53D+Z后门外板冲压麻点质量异议分析-长城.pdf",
    },
    {"file_id": 103490, "user_id": 13742, "file_name": "【隐裂反查报告】-ENEA前门内板-首钢.pdf"},
    {"file_id": 103491, "user_id": 13742, "file_name": "【开裂异议反查报告】-豹5左前轮罩上纵梁内板-首钢.pdf"},
    {"file_id": 103492, "user_id": 13742, "file_name": "【隐裂异议反查报告】-EQEA前门内板-首钢.pdf"},
    {"file_id": 103493, "user_id": 12620, "file_name": "GBT+34474-2025.pdf"},
    {"file_id": 103494, "user_id": 13742, "file_name": "【隐裂异议反查报告】-UNE左右C柱加板-首钢.pdf"},
    {"file_id": 103495, "user_id": 13742, "file_name": "【隐裂异议反查报告】-EQEA后门内板-首钢.pdf"},
    {"file_id": 103496, "user_id": 13742, "file_name": "鄂尔多斯奇瑞顶盖外板开裂开裂分析报告-奇瑞.pdf"},
    {"file_id": 103497, "user_id": 13742, "file_name": "【针尖状缺陷反查报告】-SRHA车型侧围外板-首钢.pdf"},
    {"file_id": 103498, "user_id": 13742, "file_name": "佛山大众VW380（ GOLF A8）前后门外板锌灰分析报告.pdf"},
    {"file_id": 103499, "user_id": 13742, "file_name": "佛山大众高8高强后门外板冲压亮点分析.pdf"},
    {"file_id": 103500, "user_id": 13742, "file_name": "佛山一汽大众VW316-6前门外板麻点缺陷分析.pdf"},
    {
        "file_id": 103501,
        "user_id": 13742,
        "file_name": "光束汽车J05车型翼子板外板冲压开裂质量异议分析与整改报告--光束.pdf",
    },
    {"file_id": 103502, "user_id": 13742, "file_name": "光束汽车J01顶盖外板冲压开裂质量异议分析与整改报告--光束.pdf"},
    {"file_id": 103503, "user_id": 13742, "file_name": "光束汽车J05车型右后门内板冲压隐裂质量异议分析报告--光束.pdf"},
    {"file_id": 103504, "user_id": 13742, "file_name": "关于J05车型前门外板锌渣问题的专题汇报.pdf"},
    {
        "file_id": 103505,
        "user_id": 13742,
        "file_name": "光束汽车光束汽车J05车型前门内板冲压开裂质量异议分析与整改报告--光束.pdf",
    },
    {"file_id": 103506, "user_id": 13742, "file_name": "天津大众VW326后门内板线性缺陷分析.pdf"},
    {"file_id": 103507, "user_id": 13742, "file_name": "天津大众X77后门外板亮点缺陷分析.pdf"},
    {"file_id": 103508, "user_id": 13742, "file_name": "天津大众X77前门外板线性缺陷分析.pdf"},
    {"file_id": 103509, "user_id": 12620, "file_name": "QSGZGS 0329-2020 连续热镀锌及锌合金钢板及钢带.pdf"},
    {"file_id": 103510, "user_id": 12620, "file_name": "GBT4333.8-2022硅铁 钙含量的测定 火焰原值吸收光谱法-扫描件.pdf"},
    {
        "file_id": 103511,
        "user_id": 12620,
        "file_name": "GBT8454-2020焊条用还原钛铁矿粉亚铁含量的测定重铬酸钾滴定法.pdf",
    },
    {"file_id": 103512, "user_id": 12620, "file_name": "GBT+46224-2025碳化物球化程度的评定方法-报批稿.pdf"},
    {
        "file_id": 103513,
        "user_id": 12620,
        "file_name": "GBT29652-2013直接还原铁+碳和硫含量的测定+高频燃烧红外吸收法.pdf",
    },
    {
        "file_id": 103514,
        "user_id": 12620,
        "file_name": "GBT223.92-2023钢铁及合金+镧、铈、镨、钕、钐含量的测定+电感耦合等离子体质谱法.pdf",
    },
    {"file_id": 103515, "user_id": 12620, "file_name": "GBT+46598-2025.pdf"},
    {"file_id": 103516, "user_id": 12620, "file_name": "GBT 226-2015钢的低倍组织及缺陷酸蚀检验法.pdf"},
    {"file_id": 103517, "user_id": 13742, "file_name": "天津大众奥迪Q3后门外板表面线性缺陷及麻点分析.pdf"},
    {"file_id": 103518, "user_id": 13742, "file_name": "西安比亚迪UGEA前门内板起皱问题分析报告.pdf"},
    {"file_id": 103519, "user_id": 13742, "file_name": "长春大众CCFB前门内板CR4冲压缩孔分析.pdf"},
    {
        "file_id": 103520,
        "user_id": 13742,
        "file_name": "长城泰州ES11左右前门外板线性缺陷质量异议分析与整改报告—长城.pdf",
    },
    {"file_id": 103521, "user_id": 13742, "file_name": "长春大众CCFB前门内板CR4冲压缩孔分析-20250311.pdf"},
    {"file_id": 103522, "user_id": 13742, "file_name": "长春大众CC后盖内板CR4冲压缩孔分析.pdf"},
    {"file_id": 103523, "user_id": 13742, "file_name": "长春大众CCFB前门内板CR4冲压缩孔分析-20251018.pdf"},
    {"file_id": 103524, "user_id": 13742, "file_name": "郑州比亚迪SA2右侧围冲压开裂返查报告.pdf"},
    {"file_id": 103525, "user_id": 13742, "file_name": "郑州比亚迪SA6连接板冲压开裂返查报告.pdf"},
    {"file_id": 103526, "user_id": 13742, "file_name": "郑州比亚迪SA2左侧围冲压开裂返查报告.pdf"},
    {"file_id": 103527, "user_id": 13742, "file_name": "郑州比亚迪SA6左侧围冲压开裂返查报告.pdf"},
    {"file_id": 103528, "user_id": 13742, "file_name": "郑州比亚迪SA6左侧围锁扣区域夹杂开裂分析报告.pdf"},
    {"file_id": 103529, "user_id": 13742, "file_name": "郑州比亚迪SA6左前轮罩夹杂开裂分析报告.pdf"},
    {
        "file_id": 103530,
        "user_id": 13742,
        "file_name": "重庆长城P11镀锌板UF340D+Z发动机罩外板冲压鼓包凹坑质量异议分析与整改报告--长城.pdf",
    },
    {
        "file_id": 103531,
        "user_id": 13742,
        "file_name": "重庆长城P11镀锌板UF340D+Z发动机罩外板冲压开裂质量异议分析与整改报告--长城.pdf",
    },
    {
        "file_id": 103532,
        "user_id": 13742,
        "file_name": "重庆长城P11镀锌板UF340D+Z后门外板冲压开裂分析与整改报告--长城.pdf",
    },
    {
        "file_id": 103533,
        "user_id": 13742,
        "file_name": "重庆长城P3011镀锌板DC53D+Z前门外板冲压爆皮质量异议分析与整改报告—长城.pdf",
    },
    {
        "file_id": 103534,
        "user_id": 13742,
        "file_name": "重庆长城P01镀锌板UF340D+Z发动机罩外板冲压麻点异议分析与整改报告—长城.pdf",
    },
    {
        "file_id": 103535,
        "user_id": 13742,
        "file_name": "重庆长城P3011镀锌板DC53D+Z翼子板冲压开裂质量异议分析与整改报告--长城.pdf",
    },
    {
        "file_id": 103536,
        "user_id": 13742,
        "file_name": "重庆长城P3011镀锌板DC56D+Z车箱右边板外板（大双）冲压凹坑质量异议分析与整改报告—长城.pdf",
    },
    {
        "file_id": 103537,
        "user_id": 13742,
        "file_name": "重庆长城P3011镀锌板DC56D+Z右边板外板大双冲压开裂质量异议分析与整改报告--长城.pdf",
    },
    {
        "file_id": 103538,
        "user_id": 13742,
        "file_name": "重庆长城P3011镀锌板DC56D+Z右侧围外板冲压开裂质量异议分析报告--长城.pdf",
    },
    {
        "file_id": 103539,
        "user_id": 13742,
        "file_name": "重庆长城P3011连退板170P1前地板冲压隐裂质量异议分析与整改报告6.16-长城.pdf",
    },
    {
        "file_id": 103540,
        "user_id": 13742,
        "file_name": "重庆长城P3011连退板170P1前地板冲压隐裂质量异议分析与整改报告-长城.pdf",
    },
    {
        "file_id": 103541,
        "user_id": 13742,
        "file_name": "重庆长城配套平洋工贸P01左右前罩灯下安装板冲压开裂质量异议分析与整改报告--长城.pdf",
    },
    {"file_id": 103542, "user_id": 13742, "file_name": "重庆长城汽车P01发动机罩外板质量异议分析报告-长城.pdf"},
    {"file_id": 103543, "user_id": 12620, "file_name": "GBT+247-2025.pdf"},
    {"file_id": 103544, "user_id": 12620, "file_name": "GBT+38216.5-2024+钢渣+氧化锰含量的测定+火焰原子吸收光谱法.pdf"},
    {"file_id": 103545, "user_id": 12620, "file_name": "GB T 3653.1-2024硼铁 硼含量的测定 碱量滴定法.pdf"},
    {
        "file_id": 103546,
        "user_id": 12620,
        "file_name": "GBT5687.12-2020铬铁磷铝钛铜锰钙含量的测定电感耦合等离子体原子发射光谱法.pdf",
    },
    {"file_id": 103547, "user_id": 12620, "file_name": "GB_T 15574-2016 钢产品分类.pdf"},
    {"file_id": 97916, "user_id": 12620, "file_name": "GBT4333.8-2022硅铁 钙含量的测定 火焰原值吸收光谱法.pdf"},
    {"file_id": 97917, "user_id": 12620, "file_name": "GBZ 38434-2019 金属材料 力学性能试验用试样制备指南.pdf"},
    {"file_id": 97918, "user_id": 12620, "file_name": "GB T 229-2020 金属材料 夏比摆锤冲击试验方法.pdf"},
    {"file_id": 97919, "user_id": 12620, "file_name": "GB+T+5027-2025.pdf"},
    {
        "file_id": 97920,
        "user_id": 12620,
        "file_name": "GBT 5027-2007 金属材料 薄板和薄带 塑性应变比%28r值%29的测定.pdf",
    },
    {
        "file_id": 97921,
        "user_id": 12620,
        "file_name": "GBT 6730.63-2024铁矿石 铝、钙、镁、锰、磷、硅和钛含量的测定 电感耦合等离子体发射光谱法.pdf",
    },
]


def usable(department, tenant_id: int) -> bool:
    if department is None:
        return False
    return (
        int(department.tenant_id) == int(tenant_id)
        and str(department.status or "") == "active"
        and not int(department.is_deleted or 0)
    )


def resolve_organization(primary, parent, tenant_id: int) -> tuple[int | None, str]:
    """Store the primary organization. A squad stores its direct parent office."""
    if not usable(primary, tenant_id):
        return None, "primary_not_usable"
    if str(primary.org_level or "") != "squad":
        return int(primary.id), "ok"
    parent_id = getattr(primary, "parent_id", None)
    if (
        parent_id is None
        or not usable(parent, tenant_id)
        or str(parent.org_level or "") != "office"
        or int(parent.id) != int(parent_id)
    ):
        return None, "squad_parent_not_office"
    return int(parent.id), "ok"


def classify_file(file_row, expected_name: str, organization_id: int, tenant_id: int) -> tuple[str, int | None]:
    if file_row is None:
        return "file_missing", None
    if int(file_row.tenant_id) != int(tenant_id):
        return "file_tenant_mismatch", None
    if file_row.deleted_at is not None:
        return "file_deleted", None
    if file_row.file_name != expected_name:
        return "file_name_mismatch", None
    current = None if file_row.belonging_organization_id is None else int(file_row.belonging_organization_id)
    if current == int(organization_id):
        return "unchanged", current
    return "update", current


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="按纠错3.xlsx的上传人刷新文件所属组织")
    result.add_argument("--apply", action="store_true", help="写入 knowledgefile.belonging_organization_id")
    return result


async def main() -> None:
    from sqlalchemy import update
    from sqlmodel import select

    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id, strict_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.database.models.department import Department, UserDepartment
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.user.domain.models.user import User

    args = parser().parse_args()
    user_ids = sorted({int(row["user_id"]) for row in ROWS})
    file_ids = [int(row["file_id"]) for row in ROWS]
    token = set_current_tenant_id(TENANT_ID)
    updates = []
    try:
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                user_rows = (
                    await session.exec(
                        select(User.user_id, User.user_name, User.delete).where(User.user_id.in_(user_ids))
                    )
                ).all()
                users = {int(row.user_id): row for row in user_rows}
                links = (
                    await session.exec(
                        select(UserDepartment.user_id, Department)
                        .join(Department, Department.id == UserDepartment.department_id)
                        .where(UserDepartment.user_id.in_(user_ids), UserDepartment.is_primary == 1)
                    )
                ).all()
                grouped: dict[int, list] = {user_id: [] for user_id in user_ids}
                for user_id, department in links:
                    grouped[int(user_id)].append(department)
                parent_ids = {
                    int(department.parent_id)
                    for departments in grouped.values()
                    for department in departments
                    if getattr(department, "parent_id", None) is not None
                }
                parents = {}
                if parent_ids:
                    parent_rows = (
                        await session.exec(select(Department).where(Department.id.in_(sorted(parent_ids))))
                    ).all()
                    parents = {int(row.id): row for row in parent_rows if row.id is not None}

                resolved: dict[int, tuple[int | None, str, str]] = {}
                for user_id in user_ids:
                    user = users.get(user_id)
                    if user is None:
                        resolved[user_id] = (None, "user_missing", "")
                        continue
                    if int(user.delete or 0):
                        resolved[user_id] = (None, "user_deleted", user.user_name or "")
                        continue
                    usable_rows = [row for row in grouped[user_id] if usable(row, TENANT_ID)]
                    if len(usable_rows) != 1:
                        resolved[user_id] = (None, "primary_not_unique", user.user_name or "")
                        continue
                    primary = usable_rows[0]
                    parent = parents.get(int(primary.parent_id)) if primary.parent_id is not None else None
                    organization_id, reason = resolve_organization(primary, parent, TENANT_ID)
                    resolved[user_id] = (organization_id, reason, user.user_name or "")

                file_rows = (await session.exec(select(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids)))).all()
                files = {int(row.id): row for row in file_rows}

                counts: Counter = Counter()
                plans = []
                for row in ROWS:
                    file_id = int(row["file_id"])
                    user_id = int(row["user_id"])
                    organization_id, reason, user_name = resolved[user_id]
                    record = {
                        "file_id": file_id,
                        "file_name": row["file_name"],
                        "user_id": user_id,
                        "user_name": user_name,
                    }
                    if organization_id is None:
                        record.update(action="skip", reason=reason)
                        counts[f"skip:{reason}"] += 1
                        plans.append(record)
                        continue
                    action, before = classify_file(files.get(file_id), row["file_name"], organization_id, TENANT_ID)
                    record.update(action=action, before=before, organization_id=organization_id)
                    if action == "update":
                        counts["would_update"] += 1
                        updates.append(record)
                    elif action == "unchanged":
                        counts["unchanged"] += 1
                    else:
                        counts[f"skip:{action}"] += 1
                    plans.append(record)

                print(
                    json.dumps(
                        {
                            "mode": "apply" if args.apply else "preview",
                            "rows": len(ROWS),
                            "users": {
                                str(user_id): {
                                    "user_name": item[2],
                                    "organization_id": item[0],
                                    "reason": item[1],
                                }
                                for user_id, item in sorted(resolved.items())
                            },
                            **counts,
                        },
                        ensure_ascii=False,
                    )
                )
                for record in plans:
                    print(json.dumps(record, ensure_ascii=False))

                if not args.apply:
                    return
                for record in updates:
                    before = record["before"]
                    predicate = (
                        KnowledgeFile.belonging_organization_id.is_(None)
                        if before is None
                        else KnowledgeFile.belonging_organization_id == int(before)
                    )
                    file_row = files[int(record["file_id"])]
                    result = await session.exec(
                        update(KnowledgeFile)
                        .where(
                            KnowledgeFile.id == int(record["file_id"]),
                            KnowledgeFile.tenant_id == TENANT_ID,
                            KnowledgeFile.file_name == record["file_name"],
                            KnowledgeFile.deleted_at.is_(None),
                            predicate,
                        )
                        .values(
                            belonging_organization_id=int(record["organization_id"]),
                            update_time=file_row.update_time,
                        )
                    )
                    if result.rowcount != 1:
                        await session.rollback()
                        raise SystemExit(f"没有更新 file_id={record['file_id']} rowcount={result.rowcount}")
                await session.commit()
                print(json.dumps({"committed": len(updates)}, ensure_ascii=False))
    finally:
        current_tenant_id.reset(token)

    if args.apply and updates:
        from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentStat

        file_ids = [int(record["file_id"]) for record in updates]
        queued = await KnowledgeSpaceContentStat.enqueue_file_stat_async(file_ids)
        print(json.dumps({"content_stat_queued": bool(queued), "file_count": len(file_ids)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
