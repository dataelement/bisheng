from datetime import datetime
from typing import Optional
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field, select, delete

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
import secrets
import string


class ApiKeyBase(SQLModelSerializable):
    key_name: str = Field(index=True, description='API Key名称')
    api_key: str = Field(index=True, unique=True, description='API Key值')
    user_id: int = Field(index=True, description='用户ID')
    is_active: bool = Field(default=True, description='是否启用')
    last_used_at: Optional[datetime] = Field(default=None, nullable=True, description='最后使用时间')
    total_uses: int = Field(default=0, description='使用次数')
    expires_at: Optional[datetime] = Field(default=None, nullable=True, description='过期时间')
    remark: Optional[str] = Field(default=None, description='备注')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP'), onupdate=text('CURRENT_TIMESTAMP')))


class ApiKey(ApiKeyBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class ApiKeyCreate(SQLModelSerializable):
    key_name: str
    expires_at: Optional[datetime] = None
    remark: Optional[str] = None


class ApiKeyRead(SQLModelSerializable):
    id: int
    key_name: str
    api_key: str  # 会被mask处理
    user_id: int
    is_active: bool
    last_used_at: Optional[datetime]
    total_uses: int
    expires_at: Optional[datetime]
    remark: Optional[str]
    create_time: datetime
    update_time: datetime

    def mask_api_key(self):
        """遮盖API Key，只显示前8位"""
        if len(self.api_key) > 8:
            self.api_key = f"{self.api_key[:8]}{'*' * (len(self.api_key) - 8)}"
        return self


class ApiKeyUpdate(SQLModelSerializable):
    key_name: Optional[str] = None
    is_active: Optional[bool] = None
    expires_at: Optional[datetime] = None
    remark: Optional[str] = None


class ApiKeyDao:
    
    @classmethod
    def generate_api_key(cls) -> str:
        """生成API Key"""
        # 生成前缀 + 32位随机字符
        prefix = "bsk_"  # bisheng key
        random_part = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
        return f"{prefix}{random_part}"
    
    @classmethod
    def create_api_key(cls, user_id: int, api_key_create: ApiKeyCreate) -> ApiKey:
        """创建API Key"""
        api_key_value = cls.generate_api_key()
        
        api_key = ApiKey(
            key_name=api_key_create.key_name,
            api_key=api_key_value,
            user_id=user_id,
            expires_at=api_key_create.expires_at,
            remark=api_key_create.remark
        )
        
        with session_getter() as session:
            session.add(api_key)
            session.commit()
            session.refresh(api_key)
            return api_key
    
    @classmethod
    def get_user_api_keys(cls, user_id: int) -> list[ApiKey]:
        """获取用户的所有API Key"""
        with session_getter() as session:
            statement = select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.create_time.desc())
            return session.exec(statement).all()
    
    @classmethod
    def get_api_key_by_value(cls, api_key_value: str) -> Optional[ApiKey]:
        """根据API Key值获取记录"""
        with session_getter() as session:
            statement = select(ApiKey).where(ApiKey.api_key == api_key_value, ApiKey.is_active == True)
            return session.exec(statement).first()
    
    @classmethod
    def get_api_key_by_id(cls, api_key_id: int) -> Optional[ApiKey]:
        """根据ID获取API Key"""
        with session_getter() as session:
            statement = select(ApiKey).where(ApiKey.id == api_key_id)
            return session.exec(statement).first()
    
    @classmethod
    def update_api_key(cls, api_key_id: int, api_key_update: ApiKeyUpdate) -> Optional[ApiKey]:
        """更新API Key"""
        with session_getter() as session:
            api_key = session.get(ApiKey, api_key_id)
            if not api_key:
                return None
            
            if api_key_update.key_name is not None:
                api_key.key_name = api_key_update.key_name
            if api_key_update.is_active is not None:
                api_key.is_active = api_key_update.is_active
            if api_key_update.expires_at is not None:
                api_key.expires_at = api_key_update.expires_at
            if api_key_update.remark is not None:
                api_key.remark = api_key_update.remark
            
            session.add(api_key)
            session.commit()
            session.refresh(api_key)
            return api_key
    
    @classmethod
    def delete_api_key(cls, api_key_id: int) -> bool:
        """删除API Key"""
        with session_getter() as session:
            statement = delete(ApiKey).where(ApiKey.id == api_key_id)
            result = session.exec(statement)
            session.commit()
            return result.rowcount > 0
    
    @classmethod
    def update_usage(cls, api_key_id: int):
        """更新使用统计"""
        with session_getter() as session:
            api_key = session.get(ApiKey, api_key_id)
            if api_key:
                api_key.total_uses += 1
                api_key.last_used_at = datetime.now()
                session.add(api_key)
                session.commit()
    
    @classmethod
    def validate_api_key(cls, api_key_value: str) -> Optional[ApiKey]:
        """验证API Key是否有效"""
        api_key = cls.get_api_key_by_value(api_key_value)
        
        if not api_key:
            return None
        
        # 检查是否过期
        if api_key.expires_at and api_key.expires_at < datetime.now():
            return None
        
        # 检查是否启用
        if not api_key.is_active:
            return None
        
        return api_key
