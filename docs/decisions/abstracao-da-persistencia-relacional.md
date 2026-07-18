# Abstração da persistência relacional por meio de repositories

## Status

Aceita.

## Contexto

Os casos de uso consultam vendas, clientes e produtos sem poder depender de sessões,
modelos ORM, SQLAlchemy ou detalhes de um dialeto. O planner também não pode produzir SQL
arbitrário nem receber acesso direto ao banco.

## Decisão

A aplicação depende de portas orientadas ao domínio:

- `SaleReadRepository`, `CustomerReadRepository` e `ProductReadRepository` oferecem leituras
  de registros com critérios tipados;
- `SalesAnalyticsRepository` oferece `aggregate` e `compare` para a álgebra limitada, além de
  `top_products` para o caso de uso estruturado;
- `RelationalReadUnitOfWork` reúne essas portas e controla o ciclo de vida da leitura;
- `RelationalPersistence` cria a unidade de trabalho.

SQLAlchemy implementa essas portas. Totais, contagens, médias, agrupamentos, comparações e
rankings são calculados no banco sobre `sales`, com joins apenas para `products` e `customers`.
`compare` usa uma agregação condicional por página e paginação por keyset; os casos de uso não
percorrem páginas de vendas para recalcular métricas em Python.

```text
GetSalesInsights ----> plano tipado --+
                                      +-> SalesAnalyticsRepository -> sales
GetTopProducts -----------------------+
```

Não existe repository CRUD genérico. Uma nova operação de dados somente deve ser adicionada
quando um comportamento da aplicação a exigir explicitamente.

## Consequências

- Casos de uso e domínio permanecem independentes do ORM e do banco.
- O modelo não recebe SQL, sessão ou acesso arbitrário à persistência.
- As agregações ficam concentradas e otimizáveis no adaptador relacional.
- Fakes podem substituir as portas em testes dos casos de uso.
- Uma necessidade nova exige evolução coordenada do contrato e de seus adaptadores.

## Decisões relacionadas

- [Álgebra limitada para insights de vendas em linguagem natural](./consultando-db-com-linguagem-natural.md)
- [Comparação de vendas com agregação condicional e cursor](./comparacao-de-vendas-com-agregacao-condicional-e-cursor.md)
- [GetTopProducts independente de modelo de linguagem](./get-top-products-independente-de-llm.md)
