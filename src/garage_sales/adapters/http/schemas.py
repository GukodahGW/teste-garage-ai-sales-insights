from typing import Any

from pydantic import BaseModel, ConfigDict, Field

MAX_QUESTION_LENGTH = 2_000
MAX_CURSOR_LENGTH = 4_096


class SalesInsightsQuery(BaseModel):
    """Validated query string accepted by GET /sales-insights."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(
        min_length=1,
        max_length=MAX_QUESTION_LENGTH,
        description="Pergunta sobre vendas escrita em linguagem natural.",
        examples=["Qual foi o produto mais vendido na ultima semana?"],
    )
    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_CURSOR_LENGTH,
        description="Cursor opaco retornado pela pagina anterior da mesma comparacao.",
    )
    include_plan: bool = Field(
        default=False,
        description="Inclui o plano analitico tipado para diagnostico e avaliacao.",
    )


class SalesInsightResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer: str = Field(description="Resposta produzida a partir dos dados de vendas.")
    next_cursor: str | None = Field(
        default=None,
        description="Cursor opaco para a proxima pagina da comparacao.",
    )
    plan: dict[str, Any] | None = Field(
        default=None,
        description="Plano analitico validado, presente somente quando solicitado.",
    )


class TopProductResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: int
    sku: str
    name: str
    quantity_sold: int = Field(ge=0)


class SalesMonthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    year: int = Field(ge=1, le=9999)
    month: int = Field(ge=1, le=12)


class TopProductsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_month: SalesMonthResponse | None
    products: list[TopProductResponse]


class ErrorResponse(BaseModel):
    detail: str
