from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ParseStats:
    raw: int = 0
    parsed: int = 0
    dropped_no_result: int = 0
    dropped_no_legacy: int = 0
    dropped_schema_fail: int = 0
    dropped_tombstone: int = 0
    dropped_exception: int = 0
    dropped_rt_unparseable: int = 0

    @property
    def drop_rate(self) -> float:
        if self.raw == 0:
            return 0.0
        return (self.raw - self.parsed) / self.raw * 100

    def check_drop_rate(self) -> None:
        if self.drop_rate > 80 and self.raw > 5:
            logger.warning(
                "High drop rate: %.1f%% (%d/%d dropped). "
                "no_result=%d, no_legacy=%d, schema_fail=%d, "
                "tombstone=%d, exception=%d, rt_unparseable=%d",
                self.drop_rate,
                self.raw - self.parsed,
                self.raw,
                self.dropped_no_result,
                self.dropped_no_legacy,
                self.dropped_schema_fail,
                self.dropped_tombstone,
                self.dropped_exception,
                self.dropped_rt_unparseable,
            )

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "parsed": self.parsed,
            "dropped_no_result": self.dropped_no_result,
            "dropped_no_legacy": self.dropped_no_legacy,
            "dropped_schema_fail": self.dropped_schema_fail,
            "dropped_tombstone": self.dropped_tombstone,
            "dropped_exception": self.dropped_exception,
            "dropped_rt_unparseable": self.dropped_rt_unparseable,
            "drop_rate_percent": round(self.drop_rate, 1),
        }
