# Comparação de vendas com agregação condicional e cursor

## Status

Aceita.

## Contexto

`sales.compare` precisa comparar as mesmas métricas e dimensões em dois períodos, incluindo
grupos presentes em apenas um deles. A implementação inicial executava duas agregações,
transferia todos os grupos para a aplicação, combinava os resultados em dicionários Python,
calculava as variações, ordenava e somente então aplicava `limit`.

Esse desenho era simples, porém duplicava consultas e agrupamentos. Sua memória crescia com
todos os grupos dos dois períodos, mesmo quando o consumidor precisava de poucas linhas.
Paginação por `offset` também seria inadequada: páginas profundas continuariam descartando
linhas e poderiam repetir ou omitir resultados sob uma ordenação instável.

## Decisão

`SalesAnalyticsRepository` oferece uma operação `compare`. O adapter SQLAlchemy compila cada
página para uma única instrução SQL com:

1. uma cláusula que seleciona a união dos dois intervalos;
2. agregações condicionais `CASE` para os valores atual e base de cada métrica;
3. agrupamento único pelas dimensões solicitadas;
4. cálculo SQL da diferença absoluta e da variação percentual;
5. ordenação determinística, com valores percentuais indefinidos sempre ao final;
6. `LIMIT` no banco antes da materialização de objetos Python.

`average_ticket` usa `AVG(CASE ... ELSE NULL)` para que linhas do outro período não alterem a
média. Baseline zero produz `NULL` para a variação percentual. Períodos sobrepostos são
permitidos e uma venda pode contribuir para ambos, preservando a semântica das duas consultas
independentes.

Comparações sem `limit` são entregues em páginas de até 100 linhas. `SalesAnalysisResult`
expõe `next_cursor`; o cliente o envia novamente com a mesma pergunta. O cursor contém a
última chave de ordenação, a quantidade já entregue, uma versão e a impressão digital da
consulta. Ele é opaco para clientes, usa somente comparações com parâmetros SQL e é rejeitado
quando malformado ou empregado em outra consulta.

O cursor não faz parte da álgebra produzida pela LLM. Ele entra separadamente pelo adapter
HTTP e pelo executor, portanto o modelo não cria nem interpreta estado de paginação.

```text
pergunta + cursor opcional
          |
          v
plano CompareSales -> SalesAnalyticsRepository.compare
                         |
                         v
              uma agregação SQL + keyset + LIMIT 101
                         |
                         v
               até 100 linhas + next_cursor
```

O cursor é de continuação, não um snapshot. Cada página reexecuta a agregação sobre o estado
atual do banco. Quando consistência entre páginas for um requisito, a evolução deverá usar uma
transação longa ou materializar o resultado identificado pela consulta.

## Alternativas consideradas

- Duas agregações e merge em Python: descartada pelo custo de banco, rede, CPU e memória.
- `FULL OUTER JOIN` entre duas subconsultas: desnecessário, pois agregações condicionais
  preservam grupos dos dois períodos e são portáveis para SQLite, PostgreSQL e MySQL.
- Paginação por `offset`: descartada pelo custo de páginas profundas e pela instabilidade sob
  mudanças concorrentes.
- Cursor de servidor mantido entre requisições HTTP: descartado porque prenderia conexão e
  transação ao tempo de interação do cliente.
- Tabela materializada de resultados: adiada até existir requisito de snapshot ou medições que
  justifiquem estado adicional.

## Consequências

- Cada página executa uma única consulta e materializa no máximo 100 linhas de comparação.
- Ordenação e limite não exigem listas ou dicionários proporcionais ao resultado na aplicação.
- A primeira página ainda precisa ler e agrupar todas as vendas relevantes; cursor não elimina
  esse trabalho quando a ordenação depende de uma métrica calculada.
- Percorrer todas as páginas reexecuta a agregação a cada requisição e pode ser mais caro do que
  exportar o resultado com um cursor de servidor.
- A ordenação inclui dimensões e identidades internas como desempate, evitando duplicação entre
  páginas.
- Cursores podem ser invalidados por mudança de versão ou mudança da consulta.

## Verificação

Testes de integração verificam que uma página usa uma instrução SQL, que 105 grupos são
entregues como 100 mais 5 sem duplicação, que grupos exclusivos de um período são mantidos e
que um cursor não pode continuar outra consulta.

## Decisões relacionadas

- [Álgebra limitada para insights de vendas em linguagem natural](./consultando-db-com-linguagem-natural.md)
- [Abstração da persistência relacional por meio de repositories](./abstracao-da-persistencia-relacional.md)
- [Implementações substituíveis para as etapas não determinísticas](./abstracao-das-etapas-nao-deterministicas.md)
