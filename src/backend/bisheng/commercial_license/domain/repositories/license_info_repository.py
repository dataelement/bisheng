from datetime import datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.commercial_license.domain.models.license_info import LicenseInfo


class LicenseInfoRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all(self) -> list[LicenseInfo]:
        result = await self.session.exec(select(LicenseInfo))
        return list(result.all())

    async def get_by_code(self, code: str) -> LicenseInfo | None:
        return await self.session.get(LicenseInfo, code)

    async def upsert(self, row: LicenseInfo) -> LicenseInfo:
        existing = await self.get_by_code(row.license_code)
        now = datetime.now()
        if existing is None:
            if row.checked_at is None:
                row.checked_at = now
            self.session.add(row)
            await self.session.commit()
            await self.session.refresh(row)
            return row
        existing.expire_date = row.expire_date
        existing.days_remaining = row.days_remaining
        existing.display_state = row.display_state
        existing.source_status = row.source_status
        existing.checked_at = row.checked_at or now
        existing.extra = row.extra
        self.session.add(existing)
        await self.session.commit()
        await self.session.refresh(existing)
        return existing
