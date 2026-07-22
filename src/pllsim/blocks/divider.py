"""Multi-modulus divider: bookkeeping plus additive phase noise."""
from __future__ import annotations

from dataclasses import dataclass

from ..core.noise import FlickerFloorPhase


@dataclass
class DividerConfig:
    n_int: int
    pn_floor_dbchz: float = -155.0    # output-referred... referred to divider output
    pn_fc: float = 50e3

    def noise_source(self) -> FlickerFloorPhase:
        return FlickerFloorPhase.from_spot("divider", self.pn_floor_dbchz, self.pn_fc)
