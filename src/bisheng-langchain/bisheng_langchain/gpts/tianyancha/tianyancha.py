from pydantic import BaseModel


class CompanyInfo(BaseModel):
    search_api = 'http://open.api.tianyancha.com/services/open/search/2.0'
    info_api = 'http://open.api.tianyancha.com/services/open/ic/baseinfo/normal'
    ipr_api = 'http://open.api.tianyancha.com/services/open/cb/ipr/3.0'
    judicial_api = 'http://open.api.tianyancha.com/services/open/cb/judicial/2.0'
    ic_api = 'http://open.api.tianyancha.com/services/open/cb/ic/2.0'
    law_suit_api = 'http://open.api.tianyancha.com/services/open/jr/lawSuit/2.0'
    changeinfo_api = 'http://open.api.tianyancha.com/services/open/ic/changeinfo/2.0'
    holder_api = 'http://open.api.tianyancha.com/services/open/ic/holder/2.0'
    all_company_api = 'http://open.api.tianyancha.com/services/v4/open/allCompanys'
    risk_api = 'http://open.api.tianyancha.com/services/v4/open/riskInfo'

    api_key: str

    def search_comp():
        """可以通过关键词获取企业列表，企业列表包括公司名称或ID、类型、成立日期、经营状态、统一社会信用代码等字段的详细信息"""

        pass

    def companey_baseinfo():
        """可以通过公司名称或ID获取企业基本信息，企业基本信息包括公司名称或ID、类型、成立日期、经营状态、注册资本、法人、工商注册号、统一社会信用代码、组织机构代码、纳税人识别号等字段信息"""

        pass

    def ip_rights():
        """可以通过公司名称或ID获取包含商标、专利、作品著作权、软件著作权、网站备案等维度的相关信息"""
        pass

    def judicial_risk():
        """可以通过公司名称或ID获取包含法律诉讼、法院公告、开庭公告、失信人、被执行人、立案信息、送达公告等维度的相关信息"""

        pass

    def ic_info():
        """可以通过公司名称或ID获取包含企业基本信息、主要人员、股东信息、对外投资、分支机构等维度的相关信息"""

        pass

    def law_suit_case():
        """可以通过公司名称或ID获取企业法律诉讼信息，法律诉讼包括案件名称、案由、案件身份、案号等字段的详细信息"""

        pass

    def company_chang_info():
        """可以通过公司名称或ID获取企业变更记录，变更记录包括工商变更事项、变更前后信息等字段的详细信息"""

        pass

    def company_holders():
        """可以通过公司名称或ID获取企业股东信息，股东信息包括股东名、出资比例、出资金额、股东总数等字段的详细信息"""

        pass

    def all_companys():
        """可以通过公司名称或ID和人名获取企业人员的所有相关公司，包括其担任法人、股东、董监高的公司信息"""

        pass

    def riskinfo():
        """可以通过关键字（公司名称、公司id、注册号或社会统一信用代码）获取企业相关天眼风险列表，包括企业自身/周边/预警风险信息。"""

        pass
