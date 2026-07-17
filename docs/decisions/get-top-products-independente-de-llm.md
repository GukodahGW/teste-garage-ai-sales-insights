# GetTopProducts independente de modelo de linguagem

## Status

Aceita para o endpoint estruturado legado `/top-products`. O fluxo analítico em linguagem
natural é regido por
[Álgebra analítica tipada para sales insights](./algebra-analitica-de-vendas.md).

## Contexto

O serviço oferece um caso de uso específico para obter os cinco produtos mais vendidos no
último mês-calendário que contém vendas. Essa operação recebe uma solicitação sem linguagem
natural, aplica regras de negócio conhecidas e retorna dados estruturados.

Embora a aplicação também ofereça o `GetSalesInsights`, que usa um modelo de linguagem para
interpretar perguntas, o ranking de produtos não exige interpretação probabilística. Usar um
LLM nesse fluxo acrescentaria latência, custo e possibilidade de variação sem contribuir para
o cálculo.

É necessário distinguir a dependência do caso de uso da composição do processo. O runtime
atual também constrói o adaptador de LLM usado por `GetSalesInsights`, pois os dois casos de
uso são publicados pela mesma aplicação. Essa construção compartilhada não significa que
`GetTopProducts` use o modelo durante sua execução.

## Decisão

`GetTopProductsUseCase` será totalmente determinístico e dependerá somente da porta
`RelationalPersistence`. Ele não dependerá de `SalesQueryPlanner`,
`SalesInsightSynthesizer`, LangChain, SDK de provedor, configuração de LLM ou serviço de
inferência.

O comportamento atual lê a tabela/repository legado `sales`. Novos fluxos que gravem apenas
`orders/order_items` devem usar a álgebra analítica ou evoluir deliberadamente este caso de
uso; não há sincronização automática de novas gravações para `sales`.

Durante a execução, o caso de uso deverá:

1. localizar a venda mais recente;
2. determinar os limites do respectivo mês-calendário;
3. consultar todas as páginas de vendas desse período;
4. somar as unidades vendidas por produto;
5. ordenar por quantidade decrescente, usando o identificador do produto como desempate;
6. retornar até cinco produtos existentes.

O retorno é `TopProductsResult`, contendo `reference_month` e a tupla `products`. Quando não
há vendas, ambos representam ausência de resultado (`reference_month=None` e `products=()`).

```text
Requisição -> GetTopProductsUseCase -> repositories -> banco relacional
                         |
                         +-> soma, ordenação e limite em código determinístico
```

O modelo de linguagem permanece restrito ao planejamento de consultas em linguagem natural
do fluxo `GetSalesInsights`. A indisponibilidade de um serviço de inferência não altera o
algoritmo nem os resultados de uma execução de `GetTopProducts` já composta com sua
persistência.

O fato de o runtime compartilhado construir o modelo para outro caso de uso é uma decisão do
ponto de composição. Falhas de configuração durante a inicialização do processo podem afetar
a disponibilidade da aplicação como um todo, mas não constituem uma dependência funcional de
`GetTopProducts`. Se for necessária independência operacional também na inicialização, os
pontos de composição ou processos deverão ser separados.

## Consequências positivas

- O ranking é reproduzível para o mesmo estado do banco de dados.
- O caso de uso pode ser testado sem rede, credenciais ou serviço de inferência.
- A execução não incorpora custo, latência nem falhas probabilísticas de um LLM.
- Mudanças de modelo, provedor, prompt ou framework não afetam o ranking.
- As regras de período, agregação, desempate e limite permanecem explícitas em código.

## Custos e riscos aceitos

- Novas regras de ranking exigem alteração e teste do código determinístico.
- O caso de uso não interpreta filtros ou períodos escritos em linguagem natural; essa
  necessidade pertence ao fluxo `GetSalesInsights` ou a outro caso de uso específico.
- Enquanto os dois fluxos compartilharem o mesmo runtime, uma configuração inválida do LLM
  durante a composição pode impedir a inicialização de toda a API.

## Alternativas rejeitadas

### Usar um LLM para escolher ou ordenar os produtos

Rejeitada porque os dados e critérios de ordenação já são estruturados. Um modelo não oferece
vantagem funcional e reduziria a previsibilidade do resultado.

### Reutilizar GetSalesInsights para atender o endpoint de top products

Rejeitada porque faria uma operação estruturada depender de interpretação em linguagem
natural e misturaria contratos com objetivos diferentes.

### Considerar o LLM uma dependência de GetTopProducts por estar no mesmo runtime

Rejeitada porque dependência de composição do processo e dependência funcional do caso de
uso são relações distintas. O construtor e o método `execute` de `GetTopProductsUseCase`
recebem e utilizam somente a persistência relacional.

## Decisões relacionadas

- [Álgebra analítica tipada para sales insights](./algebra-analitica-de-vendas.md)
- [Catálogo fundamental substituído](./consultando-db-com-linguagem-natural.md)
- [Implementações substituíveis para as etapas não determinísticas](./abstracao-das-etapas-nao-deterministicas.md)
- [Abstração da persistência relacional por meio de repositories](./abstracao-da-persistencia-relacional.md)

## Regra de evolução

Uma evolução de `GetTopProducts` não deverá introduzir dependência de LLM enquanto suas
entradas e regras continuarem estruturadas e determinísticas. Necessidades de interpretação
de linguagem natural deverão ser tratadas antes da execução do ranking, por uma porta ou por
um caso de uso próprio, sem transferir cálculos ou ordenação para o modelo.
