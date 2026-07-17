from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from garage_sales.domain.analytics import AnalysisStatus

MAX_QUESTION_LENGTH = 2_000


class SalesInsightsQuery(BaseModel):
    """Validated query string accepted by GET /sales-insights."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(
        min_length=1,
        max_length=MAX_QUESTION_LENGTH,
        description="Pergunta sobre vendas escrita em linguagem natural.",
        examples=["Qual foi o produto mais vendido na ultima semana?"],
    )


class SalesInsightResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer: str = Field(description="Resposta produzida a partir dos dados de vendas.")
    status: AnalysisStatus = AnalysisStatus.ANSWERED
    data: list["AnalysisDatasetResponse"] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AnalysisCellResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    value: Decimal | int | str | bool | None


class AnalysisRowResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimensions: list[AnalysisCellResponse] = Field(default_factory=list)
    metrics: list[AnalysisCellResponse] = Field(default_factory=list)


class AnalysisDatasetResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: AnalysisStatus = AnalysisStatus.ANSWERED
    rows: list[AnalysisRowResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: list[AnalysisCellResponse] = Field(default_factory=list)


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
