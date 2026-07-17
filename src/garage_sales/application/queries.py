from garage_sales.domain.criteria import CustomerCriteria, ProductCriteria, SaleCriteria
from garage_sales.domain.entities import Customer, Product, Sale
from garage_sales.domain.ports import StructuredPersistence


class SalesQueries:
    def __init__(self, persistence: StructuredPersistence) -> None:
        self._persistence = persistence

    def get_sale_by_id(self, sale_id: int) -> Sale | None:
        with self._persistence.read() as repositories:
            return repositories.sales.get_by_id(sale_id)

    def get_sales_by(self, criteria: SaleCriteria | None = None) -> list[Sale]:
        with self._persistence.read() as repositories:
            return repositories.sales.find(criteria or SaleCriteria())


class CustomerQueries:
    def __init__(self, persistence: StructuredPersistence) -> None:
        self._persistence = persistence

    def get_customer_by_id(self, customer_id: int) -> Customer | None:
        with self._persistence.read() as repositories:
            return repositories.customers.get_by_id(customer_id)

    def get_customers_by(self, criteria: CustomerCriteria | None = None) -> list[Customer]:
        with self._persistence.read() as repositories:
            return repositories.customers.find(criteria or CustomerCriteria())


class ProductQueries:
    def __init__(self, persistence: StructuredPersistence) -> None:
        self._persistence = persistence

    def get_product_by_id(self, product_id: int) -> Product | None:
        with self._persistence.read() as repositories:
            return repositories.products.get_by_id(product_id)

    def get_products_by(self, criteria: ProductCriteria | None = None) -> list[Product]:
        with self._persistence.read() as repositories:
            return repositories.products.find(criteria or ProductCriteria())

