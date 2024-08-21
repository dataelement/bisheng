"""tianyancha api"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import List, Type

from langchain_core.pydantic_v1 import BaseModel, Field
from loguru import logger

from .base import APIToolBase

asciiPattern = re.compile(r'[A-Z0-9* ]')


# 实时数据Class
class Stock(BaseModel):
    name: str
    todayStart: float
    yesterdayEnd: float
    current: float
    changeAmount: float
    changeRate: float
    vol: float
    turnover: float
    highest: float
    lowest: float
    buyPercent: float

    def __init__(self,
                 name,
                 todayStart,
                 yesterdayEnd,
                 current,
                 highest='0',
                 lowest='0',
                 vol='0',
                 turnover='0'):
        super().__init__(
            name=name,
            todayStart=float(todayStart),
            yesterdayEnd=float(yesterdayEnd),
            current=float(current),
            highest=float(highest),
            lowest=float(lowest),
            changeAmount=round(float(current) - float(yesterdayEnd), 3),
            changeRate=round((float(current) - float(yesterdayEnd)) / float(yesterdayEnd) * 100,
                             3),
            vol=float(vol),
            turnover=float(turnover),
            buyPercent=0.0,
        )

        self.buyPercent = 0.0  # 买卖盘五档委比


class StockArg(BaseModel):
    prefix: str = Field(
        description='前缀。如果是"stock_symbol"传入的为股票代码，则需要传入s_;\
如果"stock_symbol"传入的为指数代码，则为空。',
        default='',
    )
    stock_exchange: str = Field(
        description='交易所简写。股票上市的交易所，或者发布行情指数的交易所。可选项有"sh"(上海证券交易所)、" sz"( 深圳证券交易所)、"bj"( 北京证券交易所)',
    )
    stock_symbol: str = Field(description="""6位数字的股票或者指数代码。
参考信息：
- 如果问题中未给出，可能需要上网查询。
- 上交所股票通常以 6 开头，深交所股票通常以 0、3 开头，北交所股票通常以 8 开头。
- 上交所行情指数通常以 000 开头，深交所指数通常以 399 开头。同一个指数可能会同时在两个交易所发布，例如沪深 300 有"sh000300"和"sz399300"两个代码。""")


stockPattern = re.compile(
    r'var hq_str_s[hz]\d{6}="([^,"]+),([^,"]+),([^,"]+),([^,"]+),([^,"]+),([^,"]+),([^,"]+),([^,"]+),([^,"]+),([^,"]+),[^"]+";'
)
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

            return list(map(lambda x: f's_{x}', stockList))

    def devideStock(self, content: str) -> List[Stock]:
        match = stockPattern.search(content)
        stock = []
        if match:
            while match:
                stock.append(
                    Stock(match.group(1), match.group(2), match.group(3), match.group(4),
                          match.group(5), match.group(6), match.group(9), match.group(10)))
                match = stockPattern.search(content, match.end())
        else:
            stock = [content]
        return stock

    def run(self, **kwargs):
        prefix = 's_' if kwargs.get('prefix', '') == 's_' else ''
        stock_symbol = kwargs.get('stock_symbol', '')
        stock_exchange = kwargs.get('stock_exchange', '')
        stock_number = ''.join([prefix, stock_exchange, stock_symbol])

        if self.input_key == 'kLine':
            date_format = '%Y-%m-%d'
            date = kwargs.get('date')
            date_obj = datetime.strptime(date, date_format)
            ts = int(datetime.timestamp(date_obj) * 1000)
            stock = f'{stock_number}_240_{ts}'
            count = datetime.today() - date_obj
            url = self.url.format(stockName=stock_number, stock=stock, count=count.days)
            resp = self.client.get(url)
            if resp.status_code != 200:
                logger.info('api_call_fail res={}', resp.text)
            k_data = resp.text
            k_data = kLinePattern.search(k_data)
            if not k_data:
                return '{}'
            data_array = json.loads(k_data.group(1))
            for item in data_array:
                if item.get('day') == date:
                    return json.dumps(item)
            return '{}'

        resp = super().run(query=stock_number)
        stock = self.devideStock(resp)[0]
        if isinstance(stock, Stock):
            return json.dumps(stock.__dict__, ensure_ascii=False)
        else:
            return stock

    async def arun(self, **kwargs) -> str:
        prefix = 's_' if kwargs.get('prefix', '') == 's_' else ''
        stock_symbol = kwargs.get('stock_symbol', '')
        stock_exchange = kwargs.get('stock_exchange', '')
        stock_number = ''.join([prefix, stock_exchange, stock_symbol])

        if self.input_key == 'kLine':
            date_format = '%Y-%m-%d'
            date = kwargs.get('date')
            date_obj = datetime.strptime(date, date_format)
            ts = int(datetime.timestamp(date_obj) * 1000)
            stock = f'{stock_number}_240_{ts}'
            count = datetime.today() - date_obj
            url = self.url.format(stockName=stock_number, stock=stock, count=count.days)
            k_data = await self.async_client.aget(url)
            k_data = kLinePattern.search(k_data)
            if not k_data:
                return '{}'
            data_array = json.loads(k_data.group(1))
            for item in data_array:
                if item.get('day') == date:
                    return json.dumps(item)

            return '{}'
        else:
            resp = await super().arun(query=stock_number)
            stock = self.devideStock(resp)[0]
            if isinstance(stock, Stock):
                return json.dumps(stock.__dict__, ensure_ascii=False)
            else:
                return stock

    @classmethod
    def realtime_info(cls) -> StockInfo:
        """查询中国A股（沪深北交易所）股票或指数的实时行情数据，返回收盘价、涨跌额、涨跌幅、成交量、成交额"""
        url = 'https://hq.sinajs.cn'
        input_key = 'list'
        headers = {'Referer': 'http://finance.sina.com.cn'}
        return cls(url=url, input_key=input_key, headers=headers)

    @classmethod
    def history_KLine(cls) -> StockInfo:
        """查询中国A股（沪深北交易所）股票或指数的的历史行情数据，返回时间、开盘价、最高价、最低价、收盘价、成交量（股）"""
        url = 'https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_{stock}=/CN_MarketDataService.getKLineData?symbol={stockName}&scale=240&ma=no&datalen={count}'  # noqa
        input_key = 'kLine'
        header = {'Referer': 'http://finance.sina.com.cn'}

        class stockK(BaseModel):
            stock_symbol: str = Field(description="""6位数字的股票或者指数代码。
参考信息：
- 如果问题中未给出，可能需要上网查询。
- 上交所股票通常以 6 开头，深交所股票通常以 0、3 开头，北交所股票通常以 8 开头。
- 上交所行情指数通常以 000 开头，深交所指数通常以 399 开头。同一个指数可能会同时在两个交易所发布，例如沪深 300 有"sh000300"和"sz399300"两个代码。""")
            stock_exchange: str = Field(
                description=
                '交易所简写。股票上市的交易所，或者发布行情指数的交易所。可选项有"sh"(上海证券交易所)、" sz"( 深圳证券交易所)、"bj"( 北京证券交易所)', )
            date: str = Field(description='需要查询的时间，按照”2024-03-26“格式，传入日期')

        return cls(url=url, input_key=input_key, headers=header, args_schema=stockK)

    # @classmethod
    # def history_KLine(cls, stockid: str) -> StockInfo:
    #     url = 'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
    #     input_key = 'list'
    #     header = {'Referer': 'http://finance.sina.com.cn'}
    #     return cls(url=url, input_key=input_key, header=header)
