"""tianyancha api"""
from __future__ import annotations

import re

from .base import APIToolBase

asciiPattern = re.compile(r'[A-Z0-9* ]')


# 实时数据Class
class Stock:

    def __init__(self, name, todayStart, yesterdayEnd, current, highest='0', lowest='0'):
        self.name = name
        self.todayStart = float(todayStart)
        self.yesterdayEnd = float(yesterdayEnd)
        self.current = float(current)
        self.highest = float(highest)
        self.lowest = float(lowest)
        self.buyPercent = 0.0  # 买卖盘五档委比


# 计算买卖委比
class StockInfo(APIToolBase):
    'sina stock information'

    def run(self, query):
        pass

    @classmethod
    def realtime_info(cls) -> StockInfo:
        url = 'http://hq.sinajs.cn'
        input_key = 'list'
        header = {'Referer': 'http://finance.sina.com.cn'}
        return cls(url=url, input_key=input_key, header=header)

    @classmethod
    def history_KLine(cls) -> StockInfo:
        url = 'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
        input_key = 'list'
        header = {'Referer': 'http://finance.sina.com.cn'}
        return cls(url=url, input_key=input_key, header=header)

    # @classmethod
    # def history_KLine(cls, stockid: str) -> StockInfo:
    #     url = 'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
    #     input_key = 'list'
    #     header = {'Referer': 'http://finance.sina.com.cn'}
    #     return cls(url=url, input_key=input_key, header=header)
