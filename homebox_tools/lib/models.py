"""Data models for scraped product data and Homebox items."""

from dataclasses import dataclass, field


@dataclass
class ManualInfo:
    path: str
    name: str


@dataclass
class SpecField:
    name: str
    value: str
    type: str = "text"  # "text" | "number"


@dataclass
class ProductData:
    name: str
    description: str = ""
    manufacturer: str | None = None
    model: str | None = None
    price: float | None = None
    purchase_date: str | None = None
    image_path: str | None = None
    manuals: list[ManualInfo] = field(default_factory=list)
    specs: list[SpecField] = field(default_factory=list)
    suggested_tags: list[str] = field(default_factory=list)
    asin: str | None = None
    duplicate_warning: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "price": self.price,
            "purchase_date": self.purchase_date,
            "image_path": self.image_path,
            "manuals": [{"path": m.path, "name": m.name} for m in self.manuals],
            "specs": [{"name": s.name, "value": s.value, "type": s.type} for s in self.specs],
            "suggested_tags": self.suggested_tags,
            "asin": self.asin,
            "duplicate_warning": self.duplicate_warning,
        }
