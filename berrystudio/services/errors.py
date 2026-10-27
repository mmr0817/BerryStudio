"""业务异常。``str(exc)`` 可直接作为 QQ 回复文案。"""

from __future__ import annotations


class BerryError(Exception):
    def __init__(self, message: str, *, code: str = "error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code

    def __str__(self) -> str:  # pragma: no cover - 简单透传
        return self.message


class NotFoundError(BerryError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="not_found")


class PermissionDenied(BerryError):
    def __init__(self, message: str = "你没有执行该操作的权限") -> None:
        super().__init__(message, code="permission_denied")


class ConflictError(BerryError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="conflict")
