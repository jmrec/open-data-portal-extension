from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from .psgc import GeoLevel

# coarsest to finest
_ORDER = list(GeoLevel)


class Hint(BaseModel):
    """One thing a row says about where it is.

    ``level`` is ``None`` for free text, where any level may match. ``point``
    hints hold "lat,lon".
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["name", "code", "point"]
    text: str
    level: GeoLevel | None = None


class Mention(BaseModel):
    model_config = ConfigDict(frozen=True)

    hints: tuple[Hint, ...] = ()

    @property
    def key(self) -> tuple[tuple[str, str, str | None], ...]:
        return tuple((h.kind, h.text, h.level) for h in self.hints)

    @property
    def target_level(self) -> GeoLevel | None:
        """The finest named level, when every name hint states its level."""
        names = [h for h in self.hints if h.kind == "name"]
        if not names or any(h.level is None for h in names):
            return None
        return max((h.level for h in names if h.level), key=_ORDER.index)
