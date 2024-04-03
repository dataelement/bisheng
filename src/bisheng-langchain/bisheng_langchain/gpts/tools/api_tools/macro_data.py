import json
import time
from typing import Any

import pandas as pd
import requests
from langchain.pydantic_v1 import BaseModel, Field
from langchain_core.tools import BaseTool

from .base import MultArgsSchemaTool


class QueryArg(BaseModel):
    start_date: str = Field(default='', description='开始月份, 使用YYYY-MM-DD 方式表示', example='2023-01-01')
    end_date: str = Field(default='', description='结束月份，使用YYYY-MM-DD 方式表示', example='2023-05-01')


class MacroData(BaseModel):

    @classmethod
    def china_shrzgm(cls, start_date: str = '', end_date: str = '') -> pd.DataFrame:
        """中国社会融资规模增量月度统计数据。\
返回月份，社会融资规模增量(单位：亿元)，\
以及社融分项包括：人民币贷款，外币贷款，委托贷款，\
信托贷款，未贴现银行承兑汇票，企业债券，非金融企业境内股票融资
        """
        url = 'http://data.mofcom.gov.cn/datamofcom/front/gnmy/shrzgmQuery'
        r = requests.post(url)
        data_json = r.json()
        temp_df = pd.DataFrame(data_json)
        temp_df.columns = [
            '月份',
            '其中-未贴现银行承兑汇票',
            '其中-委托贷款',
            '其中-委托贷款外币贷款',
            '其中-人民币贷款',
            '其中-企业债券',
            '社会融资规模增量',
            '其中-非金融企业境内股票融资',
            '其中-信托贷款',
        ]
        temp_df = temp_df[
            [
                '月份',
                '社会融资规模增量',
                '其中-人民币贷款',
                '其中-委托贷款外币贷款',
                '其中-委托贷款',
                '其中-信托贷款',
                '其中-未贴现银行承兑汇票',
                '其中-企业债券',
                '其中-非金融企业境内股票融资',
            ]
        ]
        temp_df['社会融资规模增量'] = pd.to_numeric(temp_df['社会融资规模增量'], errors='coerce')
        temp_df['其中-人民币贷款'] = pd.to_numeric(temp_df['其中-人民币贷款'], errors='coerce')
        temp_df['其中-委托贷款外币贷款'] = pd.to_numeric(temp_df['其中-委托贷款外币贷款'], errors='coerce')
        temp_df['其中-委托贷款'] = pd.to_numeric(temp_df['其中-委托贷款'], errors='coerce')
        temp_df['其中-信托贷款'] = pd.to_numeric(temp_df['其中-信托贷款'], errors='coerce')
        temp_df['其中-未贴现银行承兑汇票'] = pd.to_numeric(temp_df['其中-未贴现银行承兑汇票'], errors='coerce')
        temp_df['其中-企业债券'] = pd.to_numeric(temp_df['其中-企业债券'], errors='coerce')
        temp_df['其中-非金融企业境内股票融资'] = pd.to_numeric(temp_df['其中-非金融企业境内股票融资'], errors='coerce')
        temp_df.sort_values(['月份'], inplace=True)
        if start_date and end_date:
            start = start_date.split('-')[0] + start_date.split('-')[1]
            end = end_date.split('-')[0] + end_date.split('-')[1]
            temp_df = temp_df[(temp_df['月份'] >= start) & (temp_df['月份'] <= end)]

        temp_df.reset_index(drop=True, inplace=True)
        return temp_df.to_markdown()

    # 金十数据中心-经济指标-中国-国民经济运行状况-经济状况-中国GDP年率报告
    @classmethod
    def china_gdp_yearly(cls, start_date: str = '', end_date: str = '') -> pd.DataFrame:
        """中国国内生产总值（GDP）季度统计数据。\
返回当年累计季度，GDP 绝对值（单位：亿元），同比增长（单位：%），\
第一产业 GDP 绝对值，（单位：亿元），第一产业同比增长（单位：%），\
第二产业 GDP 绝对值，（单位：亿元），第二产业同比增长（单位：%），\
第三产业 GDP 绝对值，（单位：亿元），第三产业同比增长（单位：%）
        """
        JS_CHINA_GDP_YEARLY_URL = 'https://cdn.jin10.com/dc/reports/dc_chinese_gdp_yoy_all.js?v={}&_={}'
        t = time.time()
        r = requests.get(JS_CHINA_GDP_YEARLY_URL.format(str(int(round(t * 1000))), str(int(round(t * 1000)) + 90)))
        json_data = json.loads(r.text[r.text.find('{') : r.text.rfind('}') + 1])
        date_list = [item['date'] for item in json_data['list']]
        value_list = [item['datas']['中国GDP年率报告'] for item in json_data['list']]
        value_df = pd.DataFrame(value_list)
        value_df.columns = json_data['kinds']
        value_df.index = pd.to_datetime(date_list)
        temp_df = value_df['今值(%)']
        url = 'https://datacenter-api.jin10.com/reports/list_v2'
        params = {
            'max_date': '',
            'category': 'ec',
            'attr_id': '57',
            '_': str(int(round(t * 1000))),
        }
        headers = {
            'accept': '*/*',
            'accept-encoding': 'gzip, deflate, br',
            'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'cache-control': 'no-cache',
            'origin': 'https://datacenter.jin10.com',
            'pragma': 'no-cache',
            'referer': 'https://datacenter.jin10.com/reportType/dc_usa_michigan_consumer_sentiment',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36',  # noqa
            'x-app-id': 'rU6QIu7JHe2gOUeR',
            'x-csrf-token': '',
            'x-version': '1.0.0',
        }
        r = requests.get(url, params=params, headers=headers)
        temp_se = pd.DataFrame(r.json()['data']['values']).iloc[:, :2]
        temp_se.index = pd.to_datetime(temp_se.iloc[:, 0])
        temp_se = temp_se.iloc[:, 1]
        temp_df = pd.concat([temp_df, temp_se])
        temp_df.dropna(inplace=True)
        temp_df.sort_index(inplace=True)
        temp_df = temp_df.reset_index()
        temp_df.columns = ['date', 'value']
        # temp_df['date'] = pd.to_datetime(temp_df['date']).dt.date
        temp_df['value'] = pd.to_numeric(temp_df['value'])
        temp_df = temp_df.drop_duplicates()
        if start_date and end_date:
            temp_df = temp_df[(temp_df['date'] >= start_date) & (temp_df['date'] <= end_date)]
        return temp_df.to_markdown()

    @classmethod
    def china_cpi(cls, start_date: str = '', end_date: str = '') -> pd.DataFrame:
        """中国居民消费价格指数(CPI，上年同月=100)月度统计数据。\
返回月份，全国当月 CPI，全国当月同比增长，全国当月环比增长，全国当年 CPI 累计值；\
城市当月 CPI，城市当月同比增长，城市当月环比增长，城市当年 CPI 累计值；\
农村当月 CPI，农村当月同比增长，农村当月环比增长，农村当年 CPI 累计值。
        """
        url = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
        params = {
            'columns': 'REPORT_DATE,TIME,NATIONAL_SAME,NATIONAL_BASE,NATIONAL_SEQUENTIAL,NATIONAL_ACCUMULATE,CITY_SAME,CITY_BASE,CITY_SEQUENTIAL,CITY_ACCUMULATE,RURAL_SAME,RURAL_BASE,RURAL_SEQUENTIAL,RURAL_ACCUMULATE',  # noqa
            'pageNumber': '1',
            'pageSize': '2000',
            'sortColumns': 'REPORT_DATE',
            'sortTypes': '-1',
            'source': 'WEB',
            'client': 'WEB',
            'reportName': 'RPT_ECONOMY_CPI',
            'p': '1',
            'pageNo': '1',
            'pageNum': '1',
            '_': '1669047266881',
        }
        r = requests.get(url, params=params)
        data_json = r.json()
        temp_df = pd.DataFrame(data_json['result']['data'])
        temp_df.columns = [
            '-',
            '月份',
            '全国-同比增长',
            '全国-当月',
            '全国-环比增长',
            '全国-累计',
            '城市-同比增长',
            '城市-当月',
            '城市-环比增长',
            '城市-累计',
            '农村-同比增长',
            '农村-当月',
            '农村-环比增长',
            '农村-累计',
        ]
        temp_df = temp_df[
            [
                '月份',
                '全国-当月',
                '全国-同比增长',
                '全国-环比增长',
                '全国-累计',
                '城市-当月',
                '城市-同比增长',
                '城市-环比增长',
                '城市-累计',
                '农村-当月',
                '农村-同比增长',
                '农村-环比增长',
                '农村-累计',
            ]
        ]
        temp_df['全国-当月'] = pd.to_numeric(temp_df['全国-当月'], errors='coerce')
        temp_df['全国-同比增长'] = pd.to_numeric(temp_df['全国-同比增长'], errors='coerce')
        temp_df['全国-环比增长'] = pd.to_numeric(temp_df['全国-环比增长'], errors='coerce')
        temp_df['全国-累计'] = pd.to_numeric(temp_df['全国-累计'], errors='coerce')
        temp_df['城市-当月'] = pd.to_numeric(temp_df['城市-当月'], errors='coerce')
        temp_df['城市-同比增长'] = pd.to_numeric(temp_df['城市-同比增长'], errors='coerce')
        temp_df['城市-环比增长'] = pd.to_numeric(temp_df['城市-环比增长'], errors='coerce')
        temp_df['城市-累计'] = pd.to_numeric(temp_df['城市-累计'], errors='coerce')
        temp_df['农村-当月'] = pd.to_numeric(temp_df['农村-当月'], errors='coerce')
        temp_df['农村-同比增长'] = pd.to_numeric(temp_df['农村-同比增长'], errors='coerce')
        temp_df['农村-环比增长'] = pd.to_numeric(temp_df['农村-环比增长'], errors='coerce')
        temp_df['农村-累计'] = pd.to_numeric(temp_df['农村-累计'], errors='coerce')
        if start_date and end_date:
            start = start_date.split('-')[0] + '年' + start_date.split('-')[1] + '月份'
            end = end_date.split('-')[0] + '年' + end_date.split('-')[1] + '月份'
            temp_df = temp_df[(temp_df['月份'] >= start) & (temp_df['月份'] <= end)]

        return temp_df.to_markdown()

    @classmethod
    def china_ppi(cls, start_date: str = '', end_date: str = '') -> pd.DataFrame:
        """中国工业品出厂价格指数（PPI）月度统计数据。返回月份，当月 PPI，当月同比增长，当年 CPI 累计值。"""
        url = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
        params = {
            'columns': 'REPORT_DATE,TIME,BASE,BASE_SAME,BASE_ACCUMULATE',
            'pageNumber': '1',
            'pageSize': '2000',
            'sortColumns': 'REPORT_DATE',
            'sortTypes': '-1',
            'source': 'WEB',
            'client': 'WEB',
            'reportName': 'RPT_ECONOMY_PPI',
            'p': '1',
            'pageNo': '1',
            'pageNum': '1',
            '_': '1669047266881',
        }
        r = requests.get(url, params=params)
        data_json = r.json()
        temp_df = pd.DataFrame(data_json['result']['data'])
        temp_df.columns = [
            '-',
            '月份',
            '当月',
            '当月同比增长',
            '累计',
        ]
        temp_df = temp_df[
            [
                '月份',
                '当月',
                '当月同比增长',
                '累计',
            ]
        ]
        temp_df['当月'] = pd.to_numeric(temp_df['当月'], errors='coerce')
        temp_df['当月同比增长'] = pd.to_numeric(temp_df['当月同比增长'], errors='coerce')
        temp_df['累计'] = pd.to_numeric(temp_df['累计'], errors='coerce')
        if start_date and end_date:
            start = start_date.split('-')[0] + '年' + start_date.split('-')[1] + '月份'
            end = end_date.split('-')[0] + '年' + end_date.split('-')[1] + '月份'
            temp_df = temp_df[(temp_df['月份'] >= start) & (temp_df['月份'] <= end)]
        return temp_df.to_markdown()

    @classmethod
    def china_money_supply(cls, start_date: str = '', end_date: str = '') -> pd.DataFrame:
        """中国货币供应量（M2，M1，M0）月度统计数据。\
返回月份，M2 数量（单位：亿元），M2 同比（单位：%），\
M2 环比（单位：%）， M1 数量（单位：亿元），\
M1 同比（单位：%），M1 环比（单位：%）， \
M0数量（单位：亿元），M0 同比（单位：%），M0 环比（单位：%）
        """
        url = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
        params = {
            'columns': 'REPORT_DATE,TIME,BASIC_CURRENCY,BASIC_CURRENCY_SAME,BASIC_CURRENCY_SEQUENTIAL,CURRENCY,CURRENCY_SAME,CURRENCY_SEQUENTIAL,FREE_CASH,FREE_CASH_SAME,FREE_CASH_SEQUENTIAL',  # noqa
            'pageNumber': '1',
            'pageSize': '2000',
            'sortColumns': 'REPORT_DATE',
            'sortTypes': '-1',
            'source': 'WEB',
            'client': 'WEB',
            'reportName': 'RPT_ECONOMY_CURRENCY_SUPPLY',
            'p': '1',
            'pageNo': '1',
            'pageNum': '1',
            '_': '1669047266881',
        }
        r = requests.get(url, params=params)
        data_json = r.json()
        temp_df = pd.DataFrame(data_json['result']['data'])
        temp_df.columns = [
            '-',
            '月份',
            '货币和准货币(M2)-数量(亿元)',
            '货币和准货币(M2)-同比增长',
            '货币和准货币(M2)-环比增长',
            '货币(M1)-数量(亿元)',
            '货币(M1)-同比增长',
            '货币(M1)-环比增长',
            '流通中的现金(M0)-数量(亿元)',
            '流通中的现金(M0)-同比增长',
            '流通中的现金(M0)-环比增长',
        ]
        temp_df = temp_df[
            [
                '月份',
                '货币和准货币(M2)-数量(亿元)',
                '货币和准货币(M2)-同比增长',
                '货币和准货币(M2)-环比增长',
                '货币(M1)-数量(亿元)',
                '货币(M1)-同比增长',
                '货币(M1)-环比增长',
                '流通中的现金(M0)-数量(亿元)',
                '流通中的现金(M0)-同比增长',
                '流通中的现金(M0)-环比增长',
            ]
        ]

        temp_df['货币和准货币(M2)-数量(亿元)'] = pd.to_numeric(temp_df['货币和准货币(M2)-数量(亿元)'])
        temp_df['货币和准货币(M2)-同比增长'] = pd.to_numeric(temp_df['货币和准货币(M2)-同比增长'])
        temp_df['货币和准货币(M2)-环比增长'] = pd.to_numeric(temp_df['货币和准货币(M2)-环比增长'])
        temp_df['货币(M1)-数量(亿元)'] = pd.to_numeric(temp_df['货币(M1)-数量(亿元)'])
        temp_df['货币(M1)-同比增长'] = pd.to_numeric(temp_df['货币(M1)-同比增长'])
        temp_df['货币(M1)-环比增长'] = pd.to_numeric(temp_df['货币(M1)-环比增长'])
        temp_df['流通中的现金(M0)-数量(亿元)'] = pd.to_numeric(temp_df['流通中的现金(M0)-数量(亿元)'])
        temp_df['流通中的现金(M0)-同比增长'] = pd.to_numeric(temp_df['流通中的现金(M0)-同比增长'])
        temp_df['流通中的现金(M0)-环比增长'] = pd.to_numeric(temp_df['流通中的现金(M0)-环比增长'])
        if start_date and end_date:
            start = start_date.split('-')[0] + '年' + start_date.split('-')[1] + '月份'
            end = end_date.split('-')[0] + '年' + end_date.split('-')[1] + '月份'
            temp_df = temp_df[(temp_df['月份'] >= start) & (temp_df['月份'] <= end)]
        return temp_df.to_markdown()

    @classmethod
    def china_consumer_goods_retail(cls, start_date: str = '', end_date: str = '') -> pd.DataFrame:
        """中国社会消费品零售总额月度统计数据。\
返回月份，当月总额（单位：亿元），同比增长（单位：%），\
环比增长（单位：%），当年累计（单位：亿元），累计同比增长（单位：%）
        """
        url = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36',  # noqa
        }
        params = {
            'columns': 'REPORT_DATE,TIME,RETAIL_TOTAL,RETAIL_TOTAL_SAME,RETAIL_TOTAL_SEQUENTIAL,RETAIL_TOTAL_ACCUMULATE,RETAIL_ACCUMULATE_SAME',  # noqa
            'pageNumber': '1',
            'pageSize': '1000',
            'sortColumns': 'REPORT_DATE',
            'sortTypes': '-1',
            'source': 'WEB',
            'client': 'WEB',
            'reportName': 'RPT_ECONOMY_TOTAL_RETAIL',
            'p': '1',
            'pageNo': '1',
            'pageNum': '1',
            '_': '1660718498421',
        }
        r = requests.get(url, params=params, headers=headers)
        data_json = r.json()
        temp_df = pd.DataFrame(data_json['result']['data'])
        temp_df.columns = [
            '-',
            '月份',
            '当月',
            '同比增长',
            '环比增长',
            '累计',
            '累计-同比增长',
        ]
        temp_df = temp_df[
            [
                '月份',
                '当月',
                '同比增长',
                '环比增长',
                '累计',
                '累计-同比增长',
            ]
        ]
        temp_df['当月'] = pd.to_numeric(temp_df['当月'], errors='coerce')
        temp_df['同比增长'] = pd.to_numeric(temp_df['同比增长'], errors='coerce')
        temp_df['环比增长'] = pd.to_numeric(temp_df['环比增长'], errors='coerce')
        temp_df['累计'] = pd.to_numeric(temp_df['累计'], errors='coerce')
        temp_df['累计-同比增长'] = pd.to_numeric(temp_df['累计-同比增长'], errors='coerce')
        if start_date and end_date:
            start = start_date.split('-')[0] + '年' + start_date.split('-')[1] + '月份'
            end = end_date.split('-')[0] + '年' + end_date.split('-')[1] + '月份'
            temp_df = temp_df[(temp_df['月份'] >= start) & (temp_df['月份'] <= end)]

        return temp_df.to_markdown()

    @classmethod
    def get_api_tool(cls, name: str, **kwargs: Any) -> BaseTool:
        attr_name = name.split('_', 1)[-1]
        class_method = getattr(cls, attr_name)

        return MultArgsSchemaTool(name=name, description=class_method.__doc__, func=class_method, args_schema=QueryArg)


if __name__ == '__main__':
    start_date = '2023-01-01'
    end_date = '2023-05-01'
    # start_date = ''
    # end_date = ''
    # print(MacroData.china_ppi(start_date=start_date, end_date=end_date))
    # print(MacroData.china_shrzgm(start_date=start_date, end_date=end_date))
    # print(MacroData.china_consumer_goods_retail(start_date=start_date, end_date=end_date))
    # print(MacroData.china_cpi(start_date=start_date, end_date=end_date))
    # print(MacroData.china_money_supply(start_date=start_date, end_date=end_date))
    print(MacroData.china_gdp_yearly(start_date=start_date, end_date=end_date))
