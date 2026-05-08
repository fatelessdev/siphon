from __future__ import annotations

from typing import Protocol


class ProxyProvider(Protocol):
    def get_proxy(self) -> dict[str, str] | None: ...
    def report_failure(self, proxy: str) -> None: ...
    def release(self, proxy: str) -> None: ...


class NullProxyProvider:
    def get_proxy(self) -> dict[str, str] | None:
        return None

    def report_failure(self, proxy: str) -> None:
        pass

    def release(self, proxy: str) -> None:
        pass
