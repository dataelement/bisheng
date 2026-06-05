from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class BrandText(BaseModel):
    zh: str = Field(default='', max_length=20)
    en: str = Field(default='', max_length=20)

    @field_validator('zh', 'en')
    @classmethod
    def validate_plain_text(cls, value: str) -> str:
        text = value.strip()
        if '<' in text or '>' in text:
            raise ValueError('HTML is not allowed')
        return text


class BrandAsset(BaseModel):
    url: str = ''
    relative_path: str = ''
    file_name: str = ''


BrandAssetCategory = Literal[
    'favicon',
    'loginHeroLight',
    'loginHeroDark',
    'headerLogoLight',
    'headerLogoDark',
    'loadingIcon',
]


class BrandAssetOption(BrandAsset):
    is_default: bool = False


class BrandAssets(BaseModel):
    favicon: BrandAsset = Field(default_factory=BrandAsset)
    loginHeroLight: BrandAsset = Field(default_factory=BrandAsset)
    loginHeroDark: BrandAsset = Field(default_factory=BrandAsset)
    headerLogoLight: BrandAsset = Field(default_factory=BrandAsset)
    headerLogoDark: BrandAsset = Field(default_factory=BrandAsset)


class BrandLoading(BaseModel):
    icon: Optional[BrandAsset] = None
    iconOptions: list[BrandAsset] = Field(default_factory=list)
    animation: Literal['', 'animate-spin', 'animate-pulse', 'animate-bounce'] = ''


class BrandConfig(BaseModel):
    brandName: BrandText = Field(default_factory=lambda: BrandText(zh='BISHENG', en='BISHENG'))
    linsightAgentName: BrandText = Field(default_factory=lambda: BrandText(zh='灵思', en='Linsight'))
    assets: BrandAssets = Field(default_factory=BrandAssets)
    loading: BrandLoading = Field(default_factory=BrandLoading)
    URLLoadingIcon: str = ''


class BrandConfigUpdate(BaseModel):
    brandName: BrandText = Field(default_factory=lambda: BrandText(zh='BISHENG', en='BISHENG'))
    assets: BrandAssets = Field(default_factory=BrandAssets)
    loading: BrandLoading = Field(default_factory=BrandLoading)
    URLLoadingIcon: str = ''


class BrandAssetUploadResponse(BaseModel):
    url: str
    relative_path: str
    file_name: str
