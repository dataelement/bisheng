#!/usr/bin/env python3
"""Import a frozen expert list into qa_expert.

Usage (from src/backend):

    .venv/bin/python scripts/shougang_execute_qa_expert.py --dry-run

Logic:
1. Read the frozen expert rows defined in this script.
2. Use a hardcoded user_id when present. Otherwise look up the user by name
   and continue only when exactly one user matches.
3. Resolve the unit name against active departments and store its id as a
   string in depart_ment. Use None when no department matches.
4. Skip user_ids already present in qa_expert so repeated runs are idempotent.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NamedTuple

_backend_root = Path(__file__).resolve().parents[1]
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))


class ExpertSeedRow(NamedTuple):
    """One frozen expert import row."""

    user_id: int | None
    name: str
    unit: str
    position: str
    title: str
    job_family: str
    job_category: str


EXPERT_ROWS: tuple[ExpertSeedRow, ...] = (
    ExpertSeedRow(16514, "徐玺", "安全部", "有害气体检测工", "首席技师", "技能操作族", "检验技能类"),
    ExpertSeedRow(11899, "胡革辉", "董事会秘书室", "股权融资", "首席证券师", "运营管控族", "企业管理类"),
    ExpertSeedRow(11963, "程华", "环境保护部", "环保技术", "首钢科学家", "制造技术族", "生产管理类"),
    ExpertSeedRow(13222, "孔维维", "计财部", "财务管理", "首席工程师", "运营管控族", "财务管理类"),
    ExpertSeedRow(13246, "成天兵", "炼钢作业部", "冶炼技术", "首席工程师", "制造技术族", "冶炼技术类"),
    ExpertSeedRow(13382, "杨建平", "炼钢作业部", "生产组织", "首席工程师", "制造技术族", "生产管理类"),
    ExpertSeedRow(11931, "彭文涛", "炼钢作业部", "生产组织", "首席工程师", "制造技术族", "生产管理类"),
    ExpertSeedRow(13648, "郭玉明", "炼钢作业部", "作业长", "首钢工匠", "技能操作族", "工艺技能类"),
    ExpertSeedRow(14623, "刘建斌", "炼钢作业部", "作业长", "首钢工匠", "技能操作族", "工艺技能类"),
    ExpertSeedRow(13651, "却汉玉", "炼钢作业部", "作业长", "首钢工匠", "技能操作族", "工艺技能类"),
    ExpertSeedRow(13787, "李杰", "炼钢作业部", "作业长", "股份工匠", "技能操作族", "工艺技能类"),
    ExpertSeedRow(14565, "王建辉", "炼钢作业部", "作业长", "首钢工匠", "技能操作族", "工艺技能类"),
    ExpertSeedRow(13979, "王永刚", "炼钢作业部", "电气点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(14508, "李刚", "炼钢作业部", "作业长", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(14074, "张浩", "炼钢作业部", "天车工", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(14661, "何俊东", "炼钢作业部", "作业长", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(14507, "王伟森", "炼钢作业部", "作业长", "首席技能专家", "技能操作族", "工艺技能类"),
    ExpertSeedRow(13945, "李建明", "炼钢作业部", "机械点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(13699, "王震", "炼钢作业部", "炼钢工", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(13946, "肖新宇", "炼钢作业部", "机械点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(14584, "吴孔彦", "炼钢作业部", "作业长", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(12644, "程洪全", "炼铁作业部", "炼铁专业技术", "首席技术专家", "制造技术族", "冶炼技术类"),
    ExpertSeedRow(16792, "胥传军", "炼铁作业部", "机械设备点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(17425, "张锦炳", "炼铁作业部", "热风炉工", "股份工匠", "技能操作族", "工艺技能类"),
    ExpertSeedRow(17458, "王雪玮", "炼铁作业部", "炉前工", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(17562, "张小兵", "炼铁作业部", "炉前工", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(16800, "李延君", "炼铁作业部", "机械设备点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(17372, "刘刚", "炼铁作业部", "炉前工", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(17761, "于福臣", "炼铁作业部", "高炉上料", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(17142, "杜艳北", "炼铁作业部", "作业长", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(17333, "马栋斌", "炼铁作业部", "炼铁运料工", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(16744, "杨志宇", "炼铁作业部", "作业长", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(17337, "王喜军", "炼铁作业部", "作业长", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(12670, "石存广", "炼铁作业部", "高炉冶炼工", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(12236, "赵凯盛", "炼铁作业部", "高炉冶炼工", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(12233, "宋少华", "炼铁作业部", "高炉冶炼工", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(17289, "谭双喜", "炼铁作业部", "机械设备点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(17592, "白文勇", "炼铁作业部", "高炉上料", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(17704, "邓振月", "炼铁作业部", "机械设备点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(16793, "校国华", "炼铁作业部", "机械点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(17357, "张浩", "炼铁作业部", "煤水工", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(17336, "沈强", "炼铁作业部", "集中控制工", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(17518, "王文宾", "炼铁作业部", "机械点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(16816, "董立田", "炼铁作业部", "机械点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(12187, "刘铁君", "炼铁作业部", "电气设备点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(11925, "李双全", "能源部", "能源项目管理", "首席技术专家", "制造技术族", "能源技术类"),
    ExpertSeedRow(15660, "王春福", "能源部", "电气点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(15674, "王文彬", "能源部", "点检工", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(15960, "王晓辉", "能源部", "汽机运行", "首席技能专家", "技能操作族", "工艺技能类"),
    ExpertSeedRow(16162, "高智勇", "能源部", "变配电运行", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(16268, "净晓星", "能源部", "泵站操作工", "首席技能专家", "技能操作族", "工艺技能类"),
    ExpertSeedRow(15734, "刘江波", "能源部", "点检工", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(16579, "孙磊", "能源部", "机械设备点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(15907, "郭家欢", "能源部", "电气点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(15868, "王保霞", "能源部", "除盐泵站操作", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(15602, "常金元", "能源部", "制氧空分", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(15837, "杨丽丽", "能源部", "汽机运行", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(16046, "马壮", "能源部", "煤气加压工", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(16143, "袁重阳", "能源部", "作业长", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(16096, "马向辉", "能源部", "机械点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(11934, "龚坚", "迁顺技术中心", "副主任", "首钢科学家", "制造技术族", "研发设计类"),
    ExpertSeedRow(12668, "赵满祥", "迁顺技术中心", "研究员", "首席工程师", "制造技术族", "研发设计类"),
    ExpertSeedRow(13133, "于浩淼", "迁顺技术中心", "研究员", "首席工程师", "制造技术族", "研发设计类"),
    ExpertSeedRow(12536, "关建东", "迁顺技术中心", "产品研究室主任", "首席技术专家", "制造技术族", "研发设计类"),
    ExpertSeedRow(13385, "黄福祥", "迁顺技术中心", "工艺研究室主任", "首席技术专家", "制造技术族", "研发设计类"),
    ExpertSeedRow(12782, "东占萃", "热轧作业部", "设备工程技术", "首席技术专家", "设备运行族", "机械技术类"),
    ExpertSeedRow(14923, "李春元", "热轧作业部", "精轧操作", "首钢工匠", "技能操作族", "工艺技能类"),
    ExpertSeedRow(15004, "张月林", "热轧作业部", "精轧操作", "首钢工匠", "技能操作族", "工艺技能类"),
    ExpertSeedRow(14726, "屈二龙", "热轧作业部", "钳工", "首席技能专家", "技能操作族", "设备技能类"),
    ExpertSeedRow(15011, "张柏元", "热轧作业部", "精轧操作", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(15047, "焦彦龙", "热轧作业部", "精轧操作", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(16313, "王万东", "热轧作业部", "磨床操作", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(14787, "李旭峰", "热轧作业部", "热轧机械设备点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(15051, "耿岩", "热轧作业部", "精轧操作", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(12819, "种祥浩", "人力资源部（党委组织部）", "薪酬管理", "首席人力师", "运营管控族", "人力资源类"),  # noqa: RUF001
    ExpertSeedRow(12468, "李转运", "设备部", "压力容器管理", "首席工程师", "设备运行族", "机械技术类"),
    ExpertSeedRow(12824, "陈建华", "设备部", "设备功能精度管理", "首席技术专家", "设备运行族", "机械技术类"),
    ExpertSeedRow(18063, "马兵智", "首钢冷轧", "质量工程技术", "首席技术专家", "制造技术族", "轧制技术类"),
    ExpertSeedRow(11784, "柳智博", "首钢冷轧", "轧制技术", "首席工程师", "制造技术族", "轧制技术类"),
    ExpertSeedRow(11795, "李凤惠", "首钢冷轧", "电气自动化", "首席工程师", "设备运行族", "自动化技术类"),
    ExpertSeedRow(12381, "崔伦凯", "首钢冷轧", "电气自动化", "首席工程师", "设备运行族", "自动化技术类"),
    ExpertSeedRow(18028, "曾进东", "首钢冷轧", "机械点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(17799, "高国强", "首钢冷轧", "酸洗出口操作", "首钢工匠", "技能操作族", "工艺技能类"),
    ExpertSeedRow(17979, "王鹤", "首钢冷轧", "酸洗入口操作", "股份工匠", "技能操作族", "工艺技能类"),
    ExpertSeedRow(17853, "程丙献", "首钢冷轧", "维护钳工", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(17873, "李建春", "首钢冷轧", "维护钳工", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(17802, "胡常城", "首钢冷轧", "重卷操作", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(17958, "陈湘宁", "首钢冷轧", "轧机出口操作", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(17996, "孙永军", "首钢冷轧", "轧机操作", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(17945, "陈晓利", "首钢冷轧", "轧机操作", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(17865, "陈金虎", "首钢冷轧", "维护焊工", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(17956, "田光杰", "首钢冷轧", "酸洗出口操作", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(18145, "付海峰", "首钢冷轧", "镀锌操控", "首席技能专家", "技能操作族", "工艺技能类"),
    ExpertSeedRow(18164, "刘瑞龙", "首钢冷轧", "连退操控", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(18056, "李永", "首钢冷轧", "连退操控", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(18250, "郑银辉", "首钢冷轧", "机械性能检验", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(17882, "郭成", "首钢冷轧", "维护钳工", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(18176, "黄士岩", "首钢冷轧", "镀锌操控", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(None, "夏兆所", "首钢智新", "轧制技术", "首席工程师", "制造技术族", "轧制技术类"),
    ExpertSeedRow(None, "安冬洋", "首钢智新", "无取向产品研发", "首席技术专家", "制造技术族", "研发设计类"),
    ExpertSeedRow(None, "黎先浩", "首钢智新", "取向产品研发", "首钢科学家", "制造技术族", "研发设计类"),
    ExpertSeedRow(None, "王现辉", "首钢智新", "取向产品研发", "首席技术专家", "制造技术族", "研发设计类"),
    ExpertSeedRow(None, "司良英", "首钢智新", "取向产品研发", "首席技术专家", "制造技术族", "研发设计类"),
    ExpertSeedRow(None, "刘玉金", "首钢智新", "无取向应用研究", "首席工程师", "制造技术族", "研发设计类"),
    ExpertSeedRow(None, "赵鹏飞", "首钢智新", "取向产品研发", "首席工程师", "制造技术族", "研发设计类"),
    ExpertSeedRow(None, "郝晓鹏", "首钢智新", "工程技术", "首席技术专家", "设备运行族", "工程管理类"),
    ExpertSeedRow(None, "程林", "首钢智新", "产品研发工程师", "首席工程师", "制造技术族", "研发设计类"),
    ExpertSeedRow(None, "李广林", "首钢智新", "产品研发工程师", "首席技术专家", "制造技术族", "研发设计类"),
    ExpertSeedRow(None, "刘磊", "首钢智新", "系统工程师", "首席工程师", "制造技术族", "轧制技术类"),
    ExpertSeedRow(None, "徐厚军", "首钢智新", "轧钢主操", "首钢工匠", "技能操作族", "工艺技能类"),
    ExpertSeedRow(None, "刘根林", "首钢智新", "钳工", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(None, "吴红福", "首钢智新", "变配电运行", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(None, "武庆国", "首钢智新", "钳工", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(None, "王宇栋", "首钢智新", "设备点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(None, "赵凯", "首钢智新", "轧钢主操", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(None, "赵国顺", "首钢智新", "轧钢主操", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(None, "柳振方", "首钢智新", "中试操作", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(None, "赵进元", "首钢智新", "轧钢主操", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(None, "姜东友", "首钢智新", "轧钢主操", "股份工匠", "技能操作族", "工艺技能类"),
    ExpertSeedRow(None, "刘靖", "首钢智新", "设备点检", "股份工匠", "技能操作族", "设备技能类"),
    ExpertSeedRow(None, "孙同江", "首钢智新", "热处理副操", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(None, "贾会刚", "首钢智新", "设备点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(None, "董振虎", "首钢智新", "轧钢主操", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(None, "盖力建", "首钢智新", "轧钢精整副操", "首席技能专家", "技能操作族", "工艺技能类"),
    ExpertSeedRow(None, "李宁", "首钢智新", "轧钢副操", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(None, "司泽", "首钢智新", "设备点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(None, "马小云", "首钢智新", "轧钢主操", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(None, "刘新", "首钢智新", "设备点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(None, "张垚龙", "首钢智新", "设备点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(None, "徐延明", "首钢智新", "热处理副操", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(None, "李二伟", "首钢智新", "热处理主操", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(None, "解攀龙", "首钢智新", "热处理副操", "首席技师", "技能操作族", "工艺技能类"),
    ExpertSeedRow(None, "王瑞", "首钢资环", "挖掘机司机", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(None, "赵建宣", "首钢资环", "天车工", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(12690, "许国峰", "投资管理部", "工程审核评价管理", "首席工程师", "设备运行族", "工程管理类"),
    ExpertSeedRow(11737, "赵忠义", "投资管理部", "工程投资预算管理", "首席工程师", "设备运行族", "工程管理类"),
    ExpertSeedRow(None, "杨可", "投资管理部", "工程组织管理", "首席工程师", "设备运行族", "工程管理类"),
    ExpertSeedRow(11727, "黄学启", "营销中心", "产品工程师", "首席工程师", "市场管理族", "市场营销类"),
    ExpertSeedRow(12138, "陈连峰", "营销中心", "汽车板技术服务", "首席技术专家", "市场管理族", "市场营销类"),
    ExpertSeedRow(18658, "刘印良", "营销中心", "产品工程师", "首席工程师", "市场管理族", "市场营销类"),
    ExpertSeedRow(12972, "张永明", "制造部", "球团技术", "首席工程师", "制造技术族", "铁前技术类"),
    ExpertSeedRow(12935, "亢小敏", "制造部", "质量技术", "首席技术专家", "制造技术族", "质量技术类"),
    ExpertSeedRow(11923, "杜斌", "制造部", "低碳技术", "首席技术专家", "制造技术族", "生产管理类"),
    ExpertSeedRow(12959, "董晟", "制造部", "信息技术", "首席工程师", "制造技术族", "信息技术类"),
    ExpertSeedRow(15441, "高贺", "质量检验部", "电工", "股份工匠", "技能操作族", "设备技能类"),
    ExpertSeedRow(15564, "陈光", "质量检验部", "化学分析工", "首席技师", "技能操作族", "检验技能类"),
    ExpertSeedRow(15509, "卢秀艳", "质量检验部", "油品耐材检验", "首席技师", "技能操作族", "检验技能类"),
    ExpertSeedRow(15572, "焦丽", "质量检验部", "化学分析工", "首席技师", "技能操作族", "检验技能类"),
    ExpertSeedRow(15449, "岳海丰", "质量检验部", "精密点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(15451, "宣星虎", "质量检验部", "点检维护", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(15569, "庞振兴", "质量检验部", "ICP-MS分析", "首席技师", "技能操作族", "检验技能类"),
    ExpertSeedRow(15448, "李付", "质量检验部", "精密点检", "首席技师", "技能操作族", "设备技能类"),
    ExpertSeedRow(12597, "徐佳", "质量检验部", "质量检测", "首席工程师", "制造技术族", "质量技术类"),
)


ResolutionReason = Literal["not_found", "ambiguous"]
UserLookup = Callable[[str], Awaitable[Sequence[Any]]]
DepartmentLookup = Callable[[], Awaitable[Sequence[Any]]]
ExistingExpertLookup = Callable[[int], Awaitable[Any | None]]
ExpertFactory = Callable[..., Any]


@dataclass(slots=True)
class ImportStats:
    """Counters reported by the import script."""

    skipped_no_user: int = 0
    skipped_duplicate: int = 0
    skipped_ambiguous_name: int = 0
    skipped_empty_name: int = 0
    unit_not_found: int = 0


async def _resolve_user_id(
    row: ExpertSeedRow,
    lookup_users: UserLookup,
) -> tuple[int | None, ResolutionReason | None]:
    """Resolve one row to a unique integer user id."""
    if row.user_id is not None:
        return row.user_id, None

    matches = await lookup_users(row.name)
    if not matches:
        return None, "not_found"
    if len(matches) > 1:
        return None, "ambiguous"
    return int(matches[0].user_id), None


async def _prepare_experts(
    rows: Sequence[ExpertSeedRow],
    *,
    lookup_users: UserLookup,
    list_departments: DepartmentLookup,
    get_existing_expert: ExistingExpertLookup,
    expert_factory: ExpertFactory,
) -> tuple[list[Any], ImportStats]:
    """Resolve hardcoded rows and return experts that are safe to insert."""
    stats = ImportStats()
    departments = await list_departments()
    departments_by_name = {department.name: department for department in departments}
    experts: list[Any] = []

    for index, row in enumerate(rows, start=1):
        if not row.name:
            stats.skipped_empty_name += 1
            continue

        user_id, reason = await _resolve_user_id(row, lookup_users)
        if reason == "not_found":
            print(
                f"[expert_import] Skip row {index}: user not found for name '{row.name}'.",
                file=sys.stderr,
            )
            stats.skipped_no_user += 1
            continue
        if reason == "ambiguous":
            print(
                f"[expert_import] Skip row {index}: ambiguous name '{row.name}'.",
                file=sys.stderr,
            )
            stats.skipped_ambiguous_name += 1
            continue
        if user_id is None:
            raise RuntimeError(f"Resolved user id is missing for row {index}.")

        if await get_existing_expert(user_id) is not None:
            stats.skipped_duplicate += 1
            continue

        department = departments_by_name.get(row.unit)
        if row.unit and department is None:
            print(
                f"[expert_import] Row {index}: "
                f"department not found for unit '{row.unit}', "
                "setting depart_ment to None.",
                file=sys.stderr,
            )
            stats.unit_not_found += 1
            department_id = None
        else:
            department_id = str(department.id) if department is not None else None

        experts.append(
            expert_factory(
                user_id=user_id,
                expert_name=row.name,
                depart_ment=department_id,
                position=row.position or None,
                major=row.title or None,
                job_family=row.job_family or None,
                job_category=row.job_category or None,
            )
        )

    return experts, stats


async def _persist_experts(
    experts: Sequence[Any],
    *,
    repository: Any,
    dry_run: bool,
) -> int:
    """Create prepared experts unless dry-run mode is active."""
    if dry_run:
        print("[expert_import] Dry-run mode: no rows written.", flush=True)
        return len(experts)

    for expert in experts:
        await repository.create(expert)
    return len(experts)


async def _run(args: argparse.Namespace) -> int:
    print(
        f"[expert_import] Loaded {len(EXPERT_ROWS)} hardcoded rows.",
        flush=True,
    )

    from bisheng.common.services.config_service import settings
    from bisheng.core.context.manager import close_app_context, initialize_app_context
    from bisheng.core.context.tenant import (
        DEFAULT_TENANT_ID,
        bypass_tenant_filter,
        current_tenant_id,
        set_current_tenant_id,
    )
    from bisheng.database.models.department import DepartmentDao
    from bisheng.database.models.qa_expert import Expert
    from bisheng.qa_expert.domain.repositories import ExpertRepository
    from bisheng.user.domain.models.user import UserDao

    tenant_token = None
    await initialize_app_context(config=settings)
    try:
        with bypass_tenant_filter():
            tenant_token = set_current_tenant_id(DEFAULT_TENANT_ID)
            repository = ExpertRepository()
            experts, stats = await _prepare_experts(
                EXPERT_ROWS,
                lookup_users=UserDao.aget_users_by_username,
                list_departments=DepartmentDao.aget_all_active,
                get_existing_expert=repository.get_by_user_id,
                expert_factory=Expert,
            )
            inserted = await _persist_experts(
                experts,
                repository=repository,
                dry_run=args.dry_run,
            )

        print(
            f"[expert_import] Summary: inserted={inserted}, "
            f"skipped_no_user={stats.skipped_no_user}, "
            f"skipped_duplicate={stats.skipped_duplicate}, "
            f"skipped_ambiguous_name={stats.skipped_ambiguous_name}, "
            f"skipped_empty_name={stats.skipped_empty_name}, "
            f"unit_not_found={stats.unit_not_found}.",
            flush=True,
        )
    finally:
        if tenant_token is not None:
            current_tenant_id.reset(tenant_token)
        await close_app_context()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report counts without writing to the database",
    )
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
