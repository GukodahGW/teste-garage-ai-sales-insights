import argparse
import json
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import text

from garage_sales.application import SalesQueries
from garage_sales.bootstrap import build_relational_persistence
from garage_sales.config import load_runtime_env
from garage_sales.domain import SaleCriteria
from garage_sales.infrastructure.sqlalchemy.migrations import upgrade_database


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="garage-sales")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check-db", help="valida a conexao com o banco configurado")
    subparsers.add_parser("init-db", help="aplica as migracoes e os seeds pendentes")
    subparsers.add_parser("migrate-db", help="aplica as migracoes e os seeds pendentes")

    sales = subparsers.add_parser("list-sales", help="lista vendas usando os repositorios")
    sales.add_argument("--customer-id", type=int)
    sales.add_argument("--min-total", type=Decimal)
    sales.add_argument("--max-total", type=Decimal)
    sales.add_argument("--limit", type=int, default=100)
    sales.add_argument("--offset", type=int, default=0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_runtime_env()
    args = _parser().parse_args(argv)
    relational_persistence = build_relational_persistence()

    try:
        if args.command == "check-db":
            with relational_persistence.engine.connect() as connection:
                connection.execute(text("SELECT 1")).scalar_one()
            print(f"Conexao OK: {relational_persistence.engine.dialect.name}")
            return 0

        if args.command in {"init-db", "migrate-db"}:
            upgrade_database(relational_persistence.engine.url)
            print(
                f"Migracoes aplicadas e seed validado: {relational_persistence.engine.dialect.name}"
            )
            return 0

        criteria = SaleCriteria(
            customer_id=args.customer_id,
            min_total=args.min_total,
            max_total=args.max_total,
            limit=args.limit,
            offset=args.offset,
        )
        sales = SalesQueries(relational_persistence).get_sales_by(criteria)
        result = [
            {
                "id": sale.id,
                "customer_id": sale.customer_id,
                "total_amount": str(sale.total_amount),
                "sold_at": sale.sold_at.isoformat(),
            }
            for sale in sales
        ]
        print(json.dumps(result, indent=2))
        return 0
    finally:
        relational_persistence.dispose()
