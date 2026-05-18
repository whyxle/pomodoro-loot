from __future__ import annotations

from dataclasses import asdict, dataclass, field
from uuid import uuid4


@dataclass
class Rarity:
    id: str
    name: str
    weight: float
    color: str = "#888888"
    drop_sound: str = ""
    drop_bg_color: str = "#0f172a"
    drop_text_color: str = "#e4ecfb"
    drop_border_color: str = "#3b82f6"
    drop_box_width: int = 260
    drop_box_height: int = 60
    drop_font_size: int = 18
    stack_max_size: int = 10
    stack_display_max: int = 99
    stack_rarity_upgrades: list[dict] = field(default_factory=list)

    @classmethod
    def create(cls, **kwargs):
        return cls(id=str(uuid4()), **kwargs)


@dataclass
class Item:
    id: str
    name: str
    rarity_id: str
    weight: float
    image_path: str = ""
    description: str = ""
    is_currency: bool = False

    @classmethod
    def create(cls, **kwargs):
        return cls(id=str(uuid4()), **kwargs)


@dataclass
class LevelSettings:
    base_xp: int = 8
    xp_growth: float = 1.35

    def to_dict(self) -> dict:
        return asdict(self)
