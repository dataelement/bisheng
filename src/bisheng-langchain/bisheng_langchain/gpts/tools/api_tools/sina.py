"""tianyancha api"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import List, Type

from langchain_core.pydantic_v1 import BaseModel, Field

from .base import APIToolBase

asciiPattern = re.compile(r'[A-Z0-9* ]')


# 实时数据Class
class Stock(BaseModel):
    name: str
    todayStart: float
    yesterdayEnd: float
    current: float
    highest: float
    lowest: float
    buyPercent: float

    def __init__(self, name, todayStart, yesterdayEnd, current, highest='0', lowest='0'):
        super().__init__(name=name,
                         todayStart=float(todayStart),
                         yesterdayEnd=float(yesterdayEnd),
                         current=float(current),
                         highest=float(highest),
                         lowest=float(lowest),
                         buyPercent=0.0)

        self.buyPercent = 0.0  # 买卖盘五档委比


class StockArg(BaseModel):
    query: str = Field(description='股票或者指数代码')


stockPattern = re.compile(r'var hq_str_s[hz]\d{6}="([^,"]+),([^,"]+),([^,"]+),([^,"]+),[^"]+";')
kLinePattern = re.compile(r'var _s[hz]\d{6}_\d+_\d+=\((\[.*?\])\)')


# 计算买卖委比
class StockInfo(APIToolBase):
    'sina stock information'
    args_schema: Type[BaseModel] = StockArg

    def validate_stockNumber(self, stocks: List[str]):
        stockList = []
        for stockNumber in stocks:
            if len(stockNumber) == 8:
                # 8位长度的代码必须以sh或者sz开头，后面6位是数字
                if (stockNumber.startswith('sh')
                        or stockNumber.startswith('sz')) and stockNumber[2:8].isdecimal():
                    stockList.append(stockNumber)
            elif len(stockNumber) == 6:
                # 6位长度的代码必须全是数字
                if stockNumber.isdecimal():
                    # 0开头自动补sz，6开头补sh，3开头补sz，否则无效
                    if stockNumber.startswith('0'):
                        stockList.append('sz' + stockNumber)
                    elif stockNumber.startswith('6'):
                        stockList.append('sh' + stockNumber)
                    elif stockNumber.startswith('3'):
                        stockList.append('sz' + stockNumber)
            elif stockNumber == 'sh':
                stockList.append('sh000001')
            elif stockNumber == 'sz':
                stockList.append('sz399001')
            elif stockNumber == 'zx':
                stockList.append('sz399005')
            elif stockNumber == 'cy':
                stockList.append('sz399006')
            elif stockNumber == '300':
                stockList.append('sh000300')
        return stockList

    def devideStock(self, content: str) -> List[Stock]:
        match = stockPattern.search(content)
        stock = []
        while match:
            stock.append(Stock(match.group(1), match.group(2), match.group(3), match.group(4)))
            match = stockPattern.search(content, match.end())
        return stock

    def run(self, query, **kwargs):
        stock_number = self.validate_stockNumber([query])[0]

        if self.input_key == 'kLine':
            date_format = '%Y-%m-%d'
            date = kwargs.get('date')
            date_obj = datetime.strptime(date, date_format)
            ts = int(datetime.timestamp(date_obj) * 1000)
            stock = f'{stock_number}_240_{ts}'
            count = datetime.today() - date_obj
            self.url = self.url.format(stockName=stock_number, stock=stock, count=count.days)

            k_data = super().run('')
            data_array = json.loads(kLinePattern.search(k_data).group(1))
            for item in data_array:
                if item.get('day') == date:
                    return json.dumps(item)
            return '{}'

        resp = super().run(query=stock_number)
        stock = self.devideStock(resp)[0]
        return json.dumps(stock.__dict__)

    async def arun(self, query, **kwargs) -> str:
        stock_number = self.validate_stockNumber([query])[0]
        if self.input_key == 'kLine':
            date_format = '%Y-%m-%d'
            date = kwargs.get('date')
            date_obj = datetime.strptime(date, date_format)
            ts = int(datetime.timestamp(date_obj) * 1000)
            stock = f'{stock_number}_240_{ts}'
            count = datetime.today() - date_obj
            self.url = self.url.format(stockName=stock_number, stock=stock, count=count.days)
            k_data = await super().arun('')

            data_array = json.loads(kLinePattern.search(k_data).group(1))
            for item in data_array:
                if item.get('day') == date:
                    return json.dumps(item)

            return '{}'
        else:
            resp = await super().arun(query=stock_number)
            stock = self.devideStock(resp)[0]
            return json.dumps(stock.__dict__)

    @classmethod
    def realtime_info(cls) -> StockInfo:
        """获取股票的实时价格"""
        url = 'https://hq.sinajs.cn'
        input_key = 'list'
        headers = {'Referer': 'http://finance.sina.com.cn'}
        return cls(url=url, input_key=input_key, headers=headers)

    @classmethod
    def history_KLine(cls) -> StockInfo:
        """获取股票历史时间的价格K线数据"""
        url = 'https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_{stock}=/CN_MarketDataService.getKLineData?symbol={stockName}&scale=240&ma=no&datalen={count}'  # noqa
        input_key = 'kLine'
        header = {'Referer': 'http://finance.sina.com.cn'}

        class stockK(BaseModel):
            query: str = Field(description='股票或者指数代码')
            date: str = Field(description='需要查询的时间，按照”2024-03-26“格式，传入日期')

        return cls(url=url, input_key=input_key, headers=header, args_schema=stockK)

    # @classmethod
    # def history_KLine(cls, stockid: str) -> StockInfo:
    #     url = 'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
    #     input_key = 'list'
    #     header = {'Referer': 'http://finance.sina.com.cn'}
    #     return cls(url=url, input_key=input_key, header=header)
