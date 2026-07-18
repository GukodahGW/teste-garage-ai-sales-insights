# GetTopProducts independente de modelo de linguagem

## Status

Aceita para o endpoint estruturado `/top-products`.

## Contexto

O serviço oferece um caso de uso específico para obter os cinco produtos mais vendidos no
último mês-calendário que contém vendas. A entrada já é estruturada; um modelo de linguagem
não acrescentaria valor ao cálculo.

## Decisão

`GetTopProductsUseCase` dependerá somente de `RelationalPersistence`. Ele não dependerá do
planner, sintetizador, LangChain, provedor ou configuração de LLM.

Durante a execução, o caso de uso:

1. localiza a venda mais recente;
2. determina os limites do respectivo mês-calendário;
3. solicita ao `SalesAnalyticsRepository` a soma de unidades por produto;
4. recebe os resultados ordenados por quantidade decrescente e identificador crescente;
5. retorna no máximo cinco produtos.

O banco executa agrupamento, soma, ordenação e limite sobre `sales`. O retorno é
`TopProductsResult`, com `reference_month` e `products`. Sem vendas, o resultado é
`reference_month=None` e `products=()`.

Essa operação permanece separada de `aggregate` e `compare`: ela expressa diretamente a regra
do endpoint, enquanto a álgebra limitada atende perguntas em linguagem natural.

```text
Requisição -> GetTopProductsUseCase -> SalesAnalyticsRepository -> banco relacional
```

## Consequências

- O ranking é reproduzível e não depende de inferência.
- A aplicação não carrega todas as vendas do mês para calcular o ranking.
- Mudanças de modelo, provedor ou prompt não afetam esse caso de uso.
- Novas regras de ranking exigem alteração explícita do contrato SQL tipado e dos testes.

## Decisões relacionadas

- [Catálogo fundamental para sales insights](./consultando-db-com-linguagem-natural.md)
- [Abstração da persistência relacional](./abstracao-da-persistencia-relacional.md)
- [Comparação de vendas com agregação condicional e cursor](./comparacao-de-vendas-com-agregacao-condicional-e-cursor.md)
