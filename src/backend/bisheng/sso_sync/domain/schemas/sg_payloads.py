"""Schemas for SG (首钢) organization sync endpoint."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SgDepartmentFieldItem(BaseModel):
    """One SG organization row in request ``Field``."""

    model_config = ConfigDict(populate_by_name=True)

    uuid: str = ''
    code: str = ''
    pid: str = ''
    remark: str = ''
    state: str = '0'

    @field_validator(
        'uuid',
        'code',
        'pid',
        'remark',
        'state',
        mode='before',
    )
    @classmethod
    def _normalize_to_str(cls, value) -> str:
        if value is None:
            return ''
        return str(value).strip()


class SgDepartmentSyncRequest(BaseModel):
    """SG organization sync request payload."""

    model_config = ConfigDict(populate_by_name=True)

    mdm_id: int = Field(alias='mdmId')
    business_system: int = Field(alias='BusinessSystem')
    uuid: str = ''
    fields: List[SgDepartmentFieldItem] = Field(default_factory=list, alias='Field')


class SgUserFieldItem(BaseModel):
    """One SG user row in request ``Field``."""

    model_config = ConfigDict(populate_by_name=True)

    uuid: str = ''
    code: str = ''
    desc34: str = ''
    desc1: str = ''
    desc93: str = '01'

    @field_validator(
        'uuid',
        'code',
        'desc34',
        'desc1',
        'desc93',
        mode='before',
    )
    @classmethod
    def _normalize_to_str(cls, value) -> str:
        if value is None:
            return ''
        return str(value).strip()


class SgUserSyncRequest(BaseModel):
    """SG user sync request payload."""

    model_config = ConfigDict(populate_by_name=True)

    mdm_id: int = Field(alias='mdmId')
    business_system: int = Field(alias='BusinessSystem')
    uuid: str = ''
    fields: List[SgUserFieldItem] = Field(default_factory=list, alias='Field')


class SgSsoHeader(BaseModel):
    """Header of SG SSO account sync payload."""

    model_config = ConfigDict(populate_by_name=True)

    int_key: str = Field(default='', alias='INT_KEY')
    sed_name: str = Field(default='', alias='SED_NAME')
    rec_name: str = Field(default='', alias='REC_NAME')
    send_date: str = Field(default='', alias='SENDDATE')
    send_time: str = Field(default='', alias='SENDTIME')


class SgSsoRowItem(BaseModel):
    """One row of SG SSO account sync payload."""

    model_config = ConfigDict(populate_by_name=True)

    person_no: str = Field(default='', alias='PersonNO')
    user_name: str = Field(default='', alias='UserName')
    guid: str = Field(default='', alias='Guid')

    @field_validator('person_no', 'user_name', 'guid', mode='before')
    @classmethod
    def _normalize_to_str(cls, value) -> str:
        if value is None:
            return ''
        return str(value).strip()


class SgSsoAccountSyncRequest(BaseModel):
    """Request payload for SG SSO account sync."""

    model_config = ConfigDict(populate_by_name=True)

    header: SgSsoHeader = Field(default_factory=SgSsoHeader, alias='HEADER')
    rows: List[SgSsoRowItem] = Field(default_factory=list, alias='ROW')


class SgSsoAccountSyncResultItem(BaseModel):
    """One result row in SG SSO account sync response."""

    model_config = ConfigDict(populate_by_name=True)

    result: str = Field(default='0', alias='Result')
    user_name: str = Field(default='', alias='UserName')
    description: str = Field(default='success', alias='Description')
    guid: str = Field(default='', alias='Guid')


class SgSsoAccountSyncResponse(BaseModel):
    """Response payload for SG SSO account sync."""

    model_config = ConfigDict(populate_by_name=True)

    items: List[SgSsoAccountSyncResultItem] = Field(default_factory=list, alias='TIEM')


class SgDataInfoItem(BaseModel):
    """Per-row result object under ``DATAINFO``."""

    model_config = ConfigDict(populate_by_name=True)

    uuid: str = ''
    code: str = ''
    status: str = '0'
    version: str = ''
    error_text: str = Field(default='', alias='errorText')


class SgDataInfos(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    data_info: List[SgDataInfoItem] = Field(default_factory=list, alias='DATAINFO')


class SgDataPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    uuid: str = Field(default='', alias='UUID')
    data_infos: SgDataInfos = Field(default_factory=SgDataInfos, alias='DATAINFOS')


class SgEsbPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: str = Field(default='0', alias='CODE')
    desc: str = Field(default='success', alias='DESC')
    data: SgDataPayload = Field(default_factory=SgDataPayload, alias='DATA')


class SgDepartmentSyncResponse(BaseModel):
    """Top-level SG response payload."""

    model_config = ConfigDict(populate_by_name=True)

    esb: SgEsbPayload = Field(alias='ESB')

