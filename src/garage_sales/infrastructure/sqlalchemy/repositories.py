from sqlalchemy import select
from sqlalchemy.orm import Session

from garage_sales.domain.criteria import CustomerCriteria, ProductCriteria, SaleCriteria
from garage_sales.domain.entities import Customer, Product, Sale
from garage_sales.infrastructure.sqlalchemy.models import CustomerModel, ProductModel, SaleModel


def _to_sale(model: SaleModel) -> Sale:
    return Sale(
        id=model.id,
        customer_id=model.customer_id,
        total_amount=model.total_amount,
        sold_at=model.sold_at,
    )


def _to_customer(model: CustomerModel) -> Customer:
    return Customer(id=model.id, name=model.name, email=model.email)


def _to_product(model: ProductModel) -> Product:
    return Product(
        id=model.id,
        sku=model.sku,
        name=model.name,
        unit_price=model.unit_price,
        active=model.active,
    )


class SqlAlchemySaleReadRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, sale_id: int) -> Sale | None:
        model = self._session.get(SaleModel, sale_id)
        return _to_sale(model) if model else None

    def find(self, criteria: SaleCriteria) -> list[Sale]:
        statement = select(SaleModel)

        if criteria.customer_id is not None:
            statement = statement.where(SaleModel.customer_id == criteria.customer_id)
        if criteria.sold_from is not None:
            statement = statement.where(SaleModel.sold_at >= criteria.sold_from)
        if criteria.sold_until is not None:
            statement = statement.where(SaleModel.sold_at <= criteria.sold_until)
        if criteria.min_total is not None:
            statement = statement.where(SaleModel.total_amount >= criteria.min_total)
        if criteria.max_total is not None:
            statement = statement.where(SaleModel.total_amount <= criteria.max_total)

        statement = statement.order_by(SaleModel.sold_at.desc(), SaleModel.id.desc())
        statement = statement.limit(criteria.limit).offset(criteria.offset)
        return [_to_sale(model) for model in self._session.scalars(statement)]


class SqlAlchemyCustomerReadRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, customer_id: int) -> Customer | None:
        model = self._session.get(CustomerModel, customer_id)
        return _to_customer(model) if model else None

    def find(self, criteria: CustomerCriteria) -> list[Customer]:
        statement = select(CustomerModel)

        if criteria.name_contains:
            statement = statement.where(
                CustomerModel.name.icontains(criteria.name_contains, autoescape=True)
            )
        if criteria.email:
            statement = statement.where(CustomerModel.email == criteria.email)

        statement = statement.order_by(CustomerModel.name, CustomerModel.id)
        statement = statement.limit(criteria.limit).offset(criteria.offset)
        return [_to_customer(model) for model in self._session.scalars(statement)]


class SqlAlchemyProductReadRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, product_id: int) -> Product | None:
        model = self._session.get(ProductModel, product_id)
        return _to_product(model) if model else None

    def find(self, criteria: ProductCriteria) -> list[Product]:
        statement = select(ProductModel)

        if criteria.name_contains:
            statement = statement.where(
                ProductModel.name.icontains(criteria.name_contains, autoescape=True)
            )
        if criteria.active is not None:
            statement = statement.where(ProductModel.active == criteria.active)
        if criteria.min_price is not None:
            statement = statement.where(ProductModel.unit_price >= criteria.min_price)
        if criteria.max_price is not None:
            statement = statement.where(ProductModel.unit_price <= criteria.max_price)

        statement = statement.order_by(ProductModel.name, ProductModel.id)
        statement = statement.limit(criteria.limit).offset(criteria.offset)
        return [_to_product(model) for model in self._session.scalars(statement)]

