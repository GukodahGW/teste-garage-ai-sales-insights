# Validação determinística de datas com reparo limitado do plano

## Status

Aceita.

## Contexto

O planner de sales insights usa Gemma para converter uma pergunta em uma operação tipada da
álgebra analítica. A validação Pydantic já rejeitava datas impossíveis, mas devolvia ao modelo
somente a mensagem genérica do parser. Nas perguntas que comparavam fevereiro de 2025 com
janeiro de 2025, o modelo produziu `2025-02-29` em duas tentativas consecutivas. Como 2025 não
é bissexto, nenhuma tentativa chegou ao repositório e o endpoint respondeu HTTP 422.

Depois da correção do calendário, a primeira pergunta revelou um segundo erro: o modelo usou
`dimensions=["month"]` apenas porque janeiro e fevereiro apareciam como limites. Isso mudou
uma comparação total em duas linhas mensais incompletas. Portanto, validade sintática da data
não é suficiente; o plano também não pode inventar agrupamento temporal.

Uma correção silenciosa do valor gerado também seria perigosa. Trocar uma data sem uma nova
composição poderia esconder uma interpretação incorreta da pergunta e deixaria outras partes
do plano, como dimensões e ordenação, sem revisão pelo modelo.

## Decisão

O adapter LangChain mantém a validação estrutural Pydantic e acrescenta um handler
determinístico para erros de calendário. Quando uma composição falha, o handler:

1. extrai datas ISO do `llm_output` rejeitado;
2. valida ano, mês e dia pelo calendário gregoriano com `calendar.monthrange`;
3. informa a data inválida, o intervalo de dias permitido e o limite válido do mês;
4. pede à Gemma um JSON completo novo, preservando a intenção da pergunta;
5. submete a nova composição a todas as validações novamente.

O handler não altera o JSON da LLM e não executa plano parcialmente válido. Por exemplo,
`2025-02-29` produz feedback informando que fevereiro de 2025 aceita os dias 01 a 28 e que o
limite daquele mês é `2025-02-28`. `2024-02-29` permanece válido.

Depois do parsing, uma segunda validação determinística confronta dimensões temporais com os
termos explícitos da pergunta. Uma dimensão `month`, por exemplo, exige que a pergunta peça
“mês”, “meses” ou uma forma mensal equivalente. Nomes como “janeiro” e “fevereiro” delimitam
períodos, mas não autorizam agrupamento. Quando a remoção mantém o plano estruturalmente válido,
dimensões temporais não solicitadas são projetadas para fora deterministicamente. Se a dimensão
for necessária para outra estrutura do plano, como um `limit`, o validator rejeita a composição
e pede outra completa. Datas inválidas continuam sempre seguindo o fluxo de feedback e retry.

```text
pergunta
   |
   v
Gemma compõe JSON
   |
   v
parser tipado + calendário + projeção/semântica determinística
   |                         |
   | válido                  | data inválida ou projeção insegura
   v                         v
plano                    feedback específico
                             |
                             +----> Gemma recompõe JSON completo
```

Datas usadas apenas como limites de `period`, `current_period` ou `baseline_period` não criam
dimensão temporal. `day`, `week`, `month` ou `year` só entram em `dimensions` quando a pergunta
solicita agrupamento, série ou detalhamento temporal. Essa regra evita que uma comparação
total entre dois meses seja transformada em agrupamento mensal.

## Limite de retries

Retries de calendário têm orçamento próprio, separado de falhas genéricas do plano e de
retries HTTP do cliente do provider. A variável
`GARAGE_PLANNER_DATE_VALIDATION_MAX_RETRIES` configura quantas novas composições a Gemma pode
fazer depois da primeira data inválida:

- padrão: `2`;
- mínimo: `0`, que rejeita a primeira composição inválida sem nova tentativa;
- máximo: `5`, para manter latência e custo limitados.

Assim, o valor padrão permite no máximo três composições motivadas por data: a inicial e duas
recomposições. `GARAGE_LLM_MAX_RETRIES` continua controlando apenas falhas transitórias de
HTTP e transporte do cliente da API de jobs e não substitui esse orçamento.

Falhas de datas não consomem o orçamento de reparos genéricos. Ainda assim, uma execução é
limitada pela soma dos dois orçamentos e nunca entra em loop indefinido. Ao esgotar o limite, o
planner retorna `LangChainPlanningError`, convertido pelo HTTP adapter em 422.

## Alternativas consideradas

- Corrigir ou truncar a data silenciosamente no código: rejeitada porque pode alterar a
  intenção e mantém sem revisão o restante do plano produzido pela LLM.
- Repetir somente a mensagem genérica do Pydantic: rejeitada porque Gemma repetiu
  `2025-02-29` mesmo depois do primeiro erro.
- Manter uma tabela fixa com o último dia de cada mês: rejeitada porque duplicaria regras de
  anos bissextos já implementadas e testadas pela biblioteca padrão.
- Repetir até obter uma data válida: rejeitada por não limitar latência, chamadas e custo.

## Consequências

- Datas impossíveis são detectadas antes de qualquer consulta ao banco.
- O feedback é específico o suficiente para corrigir anos bissextos e meses de 28, 29, 30 ou
  31 dias.
- Toda recomposição continua sujeita ao catálogo fechado e aos modelos Pydantic estritos.
- Agrupamentos temporais obviamente não solicitados não consomem uma nova chamada quando podem
  ser removidos sem invalidar a estrutura restante.
- Uma pergunta pode consumir chamadas adicionais ao provider, limitadas pela configuração.
- Esgotar o orçamento continua sendo uma falha visível e mensurável pelo batch de avaliação.

## Verificação

Testes automatizados cobrem fevereiro inválido em ano não bissexto, 29 de fevereiro válido em
ano bissexto, recuperação na recomposição seguinte, projeção de dimensão temporal não pedida,
preservação de dimensão explicitamente pedida, esgotamento exato do limite configurado e leitura
da configuração pelo ambiente. O batch de sales insights mantém as duas perguntas de comparação
como regressões end-to-end.

## Decisões relacionadas

- [Validação determinística de filtros com reparo limitado do plano](./validacao-deterministica-de-filtros-com-reparo-limitado.md)
- [Implementações substituíveis para as etapas não determinísticas](./abstracao-das-etapas-nao-deterministicas.md)
- [Álgebra limitada para insights de vendas em linguagem natural](./consultando-db-com-linguagem-natural.md)
- [Comparação de vendas com agregação condicional e cursor](./comparacao-de-vendas-com-agregacao-condicional-e-cursor.md)
