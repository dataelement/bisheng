from typing import Literal

from pydantic import BaseModel, Field, field_validator


class BrandText(BaseModel):
    zh: str = Field(default="", max_length=20)
    en: str = Field(default="", max_length=20)

    @field_validator("zh", "en")
    @classmethod
    def validate_plain_text(cls, value: str) -> str:
        text = value.strip()
        if "<" in text or ">" in text:
            raise ValueError("HTML is not allowed")
        return text


class BrandAsset(BaseModel):
    url: str = ""
    relative_path: str = ""
    file_name: str = ""


BrandAssetCategory = Literal[
    "favicon",
    "loginHeroLight",
    "loginHeroDark",
    "headerLogoLight",
    "headerLogoDark",
    "loadingIcon",
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
    icon: BrandAsset | None = None
    iconOptions: list[BrandAsset] = Field(default_factory=list)
    animation: Literal["", "animate-spin", "animate-pulse", "animate-bounce"] = ""


class BrandConfig(BaseModel):
    brandName: BrandText = Field(default_factory=lambda: BrandText(zh="BISHENG", en="BISHENG"))
    linsightAgentName: BrandText = Field(default_factory=lambda: BrandText(zh="灵思", en="Linsight"))
    assets: BrandAssets = Field(default_factory=BrandAssets)
    loading: BrandLoading = Field(default_factory=BrandLoading)
    URLLoadingIcon: str = ""
    # Workbench (end-user /workspace app) accent theme preset. Global, admin-set;
    # the client applies it before first paint via brand-runtime.js and the
    # loading spinner follows the resulting --primary.
    workbenchTheme: Literal["blue", "green"] = "blue"


class BrandConfigUpdate(BaseModel):
    brandName: BrandText = Field(default_factory=lambda: BrandText(zh="BISHENG", en="BISHENG"))
    assets: BrandAssets = Field(default_factory=BrandAssets)
    loading: BrandLoading = Field(default_factory=BrandLoading)
    URLLoadingIcon: str = ""
    workbenchTheme: Literal["blue", "green"] = "blue"


class BrandAssetUploadResponse(BaseModel):
    url: str
    relative_path: str
    file_name: str
