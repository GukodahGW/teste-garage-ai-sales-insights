from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

MAX_PAGE_SIZE = 500


def _validate_pagination(limit: int, offset: int) -> None:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"limit deve estar entre 1 e {MAX_PAGE_SIZE}")
    if offset < 0:
        raise ValueError("offset nao pode ser negativo")


@dataclass(frozen=True, slots=True)
class SaleCriteria:
    customer_id: int | None = None
    sold_from: datetime | None = None
    sold_until: datetime | None = None
    min_total: Decimal | None = None
    max_total: Decimal | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        _validate_pagination(self.limit, self.offset)
        if self.sold_from and self.sold_until and self.sold_from > self.sold_until:
            raise ValueError("sold_from nao pode ser posterior a sold_until")
        if self.min_total is not None and self.max_total is not None:
            if self.min_total > self.max_total:
                raise ValueError("min_total nao pode ser maior que max_total")


@dataclass(frozen=True, slots=True)
class CustomerCriteria:
    name_contains: str | None = None
    email: str | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        _validate_pagination(self.limit, self.offset)


@dataclass(frozen=True, slots=True)
class ProductCriteria:
    name_contains: str | None = None
    active: bool | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        _validate_pagination(self.limit, self.offset)
        if self.min_price is not None and self.max_price is not None:
            if self.min_price > self.max_price:
                raise ValueError("min_price nao pode ser maior que max_price")

