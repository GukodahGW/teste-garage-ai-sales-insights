# Catálogo fundamental para insights de vendas em linguagem natural

## Status

Substituída por
[Álgebra analítica tipada para sales insights](./algebra-analitica-de-vendas.md). Este
documento preserva a decisão intermediária que corrigiu os cálculos simples antes da adoção
do modelo completo; seu catálogo não descreve o comportamento atual.

## Contexto

Um modelo de linguagem é útil para reconhecer formulações diferentes da mesma intenção,
mas não é um mecanismo confiável para somar valores, contar registros, calcular médias ou
ordenar rankings. Entregar linhas de venda ao modelo e pedir uma resposta transfere regras
de negócio e aritmética exata para um componente probabilístico.

O domínio deste serviço é pequeno. Não precisamos de um agente genérico capaz de montar
sequências arbitrárias de consultas. Precisamos reconhecer poucas perguntas recorrentes e
executá-las com semântica estável.

## Decisão

O modelo será usado somente como classificador e extrator de período. Ele produzirá no
máximo uma operação de um catálogo fechado:

```text
sales.calculate(metric, sold_from, sold_until)
sales.top_products(sold_from, sold_until, limit)
```

`sales.calculate` aceita somente estas métricas:

- `revenue`: soma de `sales.total_amount`;
- `sale_count`: quantidade de vendas;
- `units_sold`: soma de `sales.quantity`;
- `average_ticket`: `revenue / sale_count`, com `Decimal` e arredondamento explícito.

`sales.top_products` soma unidades por produto e aplica ordenação e limite em código
determinístico.

Período, métrica e limite são os únicos elementos que o planner pode escolher. O executor
percorre todas as páginas dos repositories antes de calcular, evitando totais parciais. Um
sintetizador determinístico formata apenas valores já calculados.

Perguntas que exijam previsão, causalidade, SQL, registros individuais, comparação entre
períodos, agrupamento por cliente ou vários insights simultâneos retornam um plano vazio e
uma explicação do catálogo suportado. Elas não são parcialmente respondidas nem encaminhadas
a um modelo para cálculo livre.

## Fluxo

```text
Pergunta
   |
   v
SalesQueryPlanner (não determinístico: classifica intenção e período)
   |
   v
SalesQueryPlan (zero ou uma operação validada)
   |
   v
RepositorySalesQueryExecutor (determinístico: pagina, soma, conta, divide e ordena)
   |
   v
SalesQueryEvidence (valores já calculados)
   |
   v
DeterministicSalesInsightSynthesizer (determinístico: formata)
   |
   v
Resposta
```

## Invariantes

- O modelo nunca recebe valores monetários ou linhas para agregar.
- O plano nunca contém mais de uma operação.
- Operações desconhecidas e planos compostos são rejeitados pelo parser tipado.
- Nenhuma página limitada de repository é tratada como conjunto completo.
- Valores monetários são calculados com `Decimal`.
- O texto final não pode alterar, recalcular ou inferir valores.
- A pergunta de regressão sobre o total de 2025 deve resultar em 33 vendas e `R$ 2.309,78`.

## Consequências

O serviço deixa de responder perguntas abertas fora do catálogo. Essa limitação é
intencional: capacidades novas devem entrar como novas primitivas determinísticas, com
contrato e testes, antes de serem ensinadas ao planner.

Em troca, respostas suportadas têm semântica verificável, testes sem inferência, menor
latência e apenas uma chamada ao modelo. Trocar Gemma por outro classificador continua
possível sem alterar cálculos, persistence ou adaptadores de entrada.
