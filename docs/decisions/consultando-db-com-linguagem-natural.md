# Álgebra limitada para insights de vendas em linguagem natural

## Status

Aceita.

## Contexto

Um modelo de linguagem é útil para reconhecer a intenção de uma pergunta, mas não deve
somar valores, ordenar rankings nem criar SQL. Ao mesmo tempo, restringir o serviço a um
único total por período deixa de fora perguntas comuns, como receita mensal, melhor semana,
produto mais vendido ou crescimento entre dois anos.

Essas perguntas podem ser respondidas com o schema existente: `sales`, `products` e
`customers`. Não é necessário criar uma entidade de pedido.

## Decisão

O planner pode produzir zero ou uma operação de uma álgebra fechada:

```text
sales.aggregate(metrics, dimensions, filters, period, sort, limit)
sales.compare(metrics, dimensions, filters, current_period, baseline_period, sort, limit)
```

O vocabulário permitido é:

- métricas: `revenue`, `sale_count`, `units_sold`, `average_ticket`;
- dimensões: `product`, `category`, `customer`, `day`, `week`, `month`, `year`;
- filtros: `product`, `category`, `customer` com `equals`, `contains` ou `in`;
- ordenação crescente ou decrescente por uma métrica ou valor de comparação;
- no máximo duas dimensões, uma delas temporal, e `limit` máximo de 100 linhas.

`sales.compare` executa uma única agregação condicional sobre a união dos dois períodos e
calcula no banco valor atual, valor base, diferença absoluta e variação percentual. Baseline
zero produz variação indefinida, nunca infinita. Sem `limit`, a comparação é entregue em
páginas de até 100 linhas por cursor de keyset; o cursor não pertence ao plano produzido pelo
modelo.

O modelo escolhe somente símbolos e argumentos desse vocabulário. O
`SalesAnalyticsRepository` compila o plano para SQLAlchemy e o banco executa filtros, joins,
agrupamentos, agregações, comparações, ordenação e limite. O sintetizador determinístico apenas
apresenta as evidências já calculadas. Cursores de continuação entram separadamente pelo
adapter, sem serem criados ou interpretados pela LLM.

## Exemplos suportados

- total vendido em 2025;
- semana de 2025 com maior receita;
- receita por mês;
- cinco produtos mais vendidos;
- faturamento por categoria e mês;
- vendas de um produto ou cliente específico;
- comparação de receita entre dois períodos;
- crescimento por produto ou categoria.

## Limites sem mudança de schema

Continuam fora do catálogo:

- produtos comprados juntos, pois não existe `order_id`;
- número real de pedidos com vários itens;
- estornos, descontos, status e moedas, pois esses atributos não existem;
- causalidade, como “por que as vendas caíram?”;
- várias análises independentes na mesma pergunta.

## Invariantes

- A LLM nunca recebe linhas de venda, conexão, ORM ou SQL.
- Um plano contém no máximo uma operação validada.
- Métricas monetárias usam `Decimal`.
- Agregações são executadas no banco sobre o schema existente.
- Cada página de `sales.compare` usa uma única instrução SQL e uma ordenação determinística.
- Nenhuma migração ou tabela adicional é exigida por essa capacidade.

## Decisões relacionadas

- [Comparação de vendas com agregação condicional e cursor](./comparacao-de-vendas-com-agregacao-condicional-e-cursor.md)
- [Implementações substituíveis para as etapas não determinísticas](./abstracao-das-etapas-nao-deterministicas.md)
- [Abstração da persistência relacional por meio de repositories](./abstracao-da-persistencia-relacional.md)
