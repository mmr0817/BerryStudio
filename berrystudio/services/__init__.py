"""业务服务层：不依赖 NoneBot，便于单元测试与 HTTP 后台复用。"""

from __future__ import annotations

from berrystudio.services.errors import BerryError

__all__ = ["BerryError"]
