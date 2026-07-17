from types import TracebackType
from typing import Self

from sqlalchemy.orm import Session, sessionmaker

from garage_sales.domain.ports import (
    CustomerReadRepository,
    ProductReadRepository,
    SaleReadRepository,
)
from garage_sales.infrastructure.sqlalchemy.repositories import (
    SqlAlchemyCustomerReadRepository,
    SqlAlchemyProductReadRepository,
    SqlAlchemySaleReadRepository,
)


class SqlAlchemyReadUnitOfWork:
    sales: SaleReadRepository
    customers: CustomerReadRepository
    products: ProductReadRepository

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None

    def __enter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("a unidade de trabalho ja esta aberta")

        self._session = self._session_factory()
        self.sales = SqlAlchemySaleReadRepository(self._session)
        self.customers = SqlAlchemyCustomerReadRepository(self._session)
        self.products = SqlAlchemyProductReadRepository(self._session)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

