from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Sale:
    id: int
    customer_id: int | None
    total_amount: Decimal
    sold_at: datetime
    product_id: int | None = None
    quantity: int = 1


@dataclass(frozen=True, slots=True)
class Customer:
    id: int
    name: str
    email: str


@dataclass(frozen=True, slots=True)
class Product:
    id: int
    sku: str
    name: str
    unit_price: Decimal | None
    active: bool
    category: str | None = None
