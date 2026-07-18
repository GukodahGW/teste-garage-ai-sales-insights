# Implementações substituíveis para as etapas não determinísticas

## Status

Aceita.

## Contexto

`GetSalesInsights` usa um modelo apenas para interpretar linguagem natural. Modelo,
provedor, SDK e framework são escolhas de integração e devem poder mudar sem alterar os
casos de uso ou o acesso a dados.

## Decisão

A aplicação define três portas:

```python
class SalesQueryPlanner(Protocol):
    def plan(self, *, question: str) -> SalesQueryPlan: ...

class SalesQueryExecutor(Protocol):
    def execute(
        self,
        *,
        plan: SalesQueryPlan,
        cursor: str | None = None,
    ) -> SalesQueryEvidence: ...

class SalesInsightSynthesizer(Protocol):
    def synthesize(self, *, question: str, evidence: SalesQueryEvidence) -> str: ...
```

O planner atual usa LangChain, mas só pode selecionar zero ou uma das operações
`sales.aggregate` e `sales.compare`. O executor consulta o `SalesAnalyticsRepository` e pode
receber separadamente um cursor emitido por uma página anterior de comparação. O sintetizador
atual é determinístico e somente formata os valores já calculados pelo banco.

```text
pergunta -> planner -> plano tipado --+-> executor -> evidência -> sintetizador -> resposta
                                      |      |             |
cursor opcional ----------------------+      +-> banco      +-> next_cursor opcional
```

Saída inválida pode receber um número pequeno de tentativas de reparo, mas nunca relaxa o
catálogo nem executa parcialmente um plano.

## Invariantes

- A LLM não recebe conexão, sessão, ORM, SQL nem linhas de vendas.
- O plano contém no máximo uma operação conhecida, com métricas, dimensões, filtros,
  períodos, ordenação e limite validados.
- Cálculos, ordenação e arredondamento permanecem determinísticos.
- O cursor nunca é produzido nem interpretado pela LLM e só continua a mesma consulta.
- Uma intenção ausente do catálogo resulta em plano vazio.
- Uma capacidade nova exige requisito, implementação e testes antes de ser ensinada ao
  modelo.

## Consequências

- Modelos e provedores podem ser trocados no adaptador.
- Planejamento, execução e síntese podem ser testados separadamente.
- O caso de uso não conhece prompts nem tipos de SDKs externos.
- O catálogo pequeno reduz o impacto de respostas incorretas e prompt injection.

## Decisões relacionadas

- [Álgebra limitada para insights de vendas em linguagem natural](./consultando-db-com-linguagem-natural.md)
- [Comparação de vendas com agregação condicional e cursor](./comparacao-de-vendas-com-agregacao-condicional-e-cursor.md)
