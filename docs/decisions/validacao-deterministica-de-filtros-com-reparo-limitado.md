# Validação determinística de filtros com reparo limitado do plano

## Status

Aceita.

## Contexto

O batch de 50 perguntas obteve respostas corretas para 46 casos, mas quatro perguntas
retornaram HTTP 200 com a mensagem incorreta de que não havia vendas. A consulta ao banco
estava funcionando; o problema era o plano produzido pela Gemma antes da execução.

Foram observados dois padrões concretos:

- o literal `Category 2` foi reduzido para o filtro `category="2"`;
- um ranking de clientes sem entidade específica ganhou o filtro inventado
  `customer="all"`.

Os casos com `Category 1` apresentaram o mesmo sintoma de filtro sem correspondência. Como
zero linhas é um resultado válido para muitas perguntas, repetir qualquer consulta vazia
seria incorreto e esconderia ausência real de dados.

O planner já possuía validação estrutural Pydantic, validação gregoriana de datas e reparos
limitados. Essas garantias não detectavam valores de filtro estruturalmente válidos, porém
ausentes ou diferentes da pergunta.

## Decisão

Antes de executar o plano, o adapter LangChain aplica uma validação determinística entre a
pergunta original e todos os filtros tipados. O processo tem quatro partes.

### 1. Extração local de restrições explícitas

Um extrator local reconhece literais não ambíguos sem enviar catálogos do banco para a LLM:

- `Category N` e o alias aprovado `Categoria N` são canonizados como `Category N`;
- `Product X` e o alias aprovado `Produto X` são canonizados como `Product X`;
- identificadores `SKU...` pertencem ao campo `product`;
- endereços de e-mail pertencem ao campo `customer`;
- múltiplos produtos ou categorias preservam todos os valores na ordem da pergunta.

Aliases em português só são extraídos quando o identificador seguinte começa por maiúscula
ou número. Assim, construções gramaticais como `por produto em 2025` não criam o falso
literal `Product em`, e `produto SKU005` gera somente `SKU005`, não `Product SKU005`.

O catálogo completo de clientes não é fornecido à Gemma. Isso evita expor nomes e e-mails que
não estavam na pergunta e preserva a separação entre interpretação e persistência.

### 2. Manifesto e projeção dos literais estruturados

As restrições extraídas são apresentadas à Gemma como um manifesto obrigatório contendo
`field`, `values` e `operator`. Ao converter a saída tipada para a álgebra de domínio, filtros
da Gemma nos campos cobertos pelo manifesto são substituídos pela projeção determinística:

- um valor recebe `equals`;
- múltiplos valores recebem `in`;
- campo, valor completo e ordem vêm do extrator, nunca da geração.

Isso não tenta adivinhar entidades livres. A projeção é limitada aos formatos locais de alta
confiança descritos acima. A Gemma continua responsável pela operação, métricas, dimensões,
períodos, ordenação e limite.

### 3. Validação do plano

Cada plano precisa satisfazer estas invariantes:

1. valores estruturados explícitos devem aparecer no campo correto e com o valor canônico
   completo;
2. múltiplos valores explícitos exigem `operator="in"`;
3. qualquer outro valor de filtro deve aparecer literalmente na pergunta, ignorando apenas
   diferenças de maiúsculas e minúsculas;
4. placeholders `all`, `any`, `todo`, `todos`, `toda`, `todas`, `qualquer` e `*` são sempre
   rejeitados;
5. uma dimensão de ranking, como `customer`, não autoriza um filtro no mesmo campo quando a
   pergunta não nomeia uma entidade específica.
6. um literal estruturado usado em outro campo é rejeitado mesmo que o texto apareça na
   pergunta.

A validação ocorre antes de abrir a unidade de leitura ou consultar vendas. Ela não depende de
um resultado vazio e, portanto, não transforma ausência legítima de dados em retry.

### 4. Feedback e recomposição completa

Fora da projeção explícita, um plano inválido não é corrigido silenciosamente. O handler
informa à Gemma o campo esperado, os valores literais necessários, os valores incorretos
produzidos e a remoção de filtros inventados. A Gemma recompõe o JSON inteiro, que passa
novamente por parsing, calendário, semântica temporal e validação de filtros.

```text
pergunta -> extrator -> manifesto -> Gemma -> saída tipada
                |                         |
                +----> projeção exata <---+
                           |
             calendário -> dimensões -> filtros
                                         |      |
                                      executor  feedback -> Gemma recompõe
```

### 5. Orçamento independente

`GARAGE_PLANNER_FILTER_VALIDATION_MAX_RETRIES` controla quantas novas composições podem
ocorrer depois do primeiro erro de filtro:

- padrão: `2`;
- mínimo: `0`;
- máximo: `5`.

Esse orçamento é independente de:

- `GARAGE_PLANNER_DATE_VALIDATION_MAX_RETRIES`, usado para datas impossíveis;
- reparos genéricos de parsing e semântica;
- `GARAGE_LLM_MAX_RETRIES`, usado somente para falhas transitórias de HTTP e transporte
  da API de jobs do provider.

Com o padrão, uma sequência motivada apenas por filtro possui no máximo uma composição inicial
e duas recomposições. Ao esgotar o limite, o endpoint retorna 422 em vez de responder 200 com
uma conclusão baseada em um filtro inventado.

## Diagnóstico e avaliação

`GET /sales-insights` aceita `include_plan=true`. A resposta inclui o plano tipado somente
quando esse parâmetro é solicitado; consumidores normais continuam recebendo apenas a resposta
e o cursor. O plano contém a álgebra validada, nunca SQL nem linhas de vendas.

O batch usa essa opção e grava o plano de cada tentativa no relatório JSON. O resumo também
calcula acurácia por capacidade, permitindo distinguir regressões de filtro, ranking,
comparação e agrupamento mesmo quando a taxa global permanece estável.

Como filtros podem conter nomes ou e-mails já presentes na pergunta, os relatórios de avaliação
devem permanecer artefatos locais ignorados pelo Git.

## Alternativas consideradas

- Repetir consultas que retornam zero linhas: rejeitada porque ausência de vendas pode ser a
  resposta correta.
- Substituir ad hoc `"2"` por `"Category 2"`: rejeitada porque uma heurística sobre a saída
  não prova qual era o literal original. A projeção adotada faz o caminho inverso: parte do
  literal explícito de alta confiança na pergunta e torna esse valor imutável.
- Enviar todos os produtos, categorias e clientes no prompt: rejeitada por custo de contexto,
  acoplamento ao banco e exposição desnecessária de dados de clientes.
- Confiar apenas em exemplos no prompt: insuficiente para uma etapa não determinística; os
  exemplos permanecem como auxílio, mas a garantia vem do validator.
- Retry ilimitado: rejeitado por custo e latência não limitados.

## Consequências

- Os quatro modos de falha observados são neutralizados ou rejeitados antes do banco.
- Literais estruturados, SKUs e e-mails não podem ser truncados nem associados a outro campo.
- Literais estruturados não consomem retry quando a única divergência da Gemma é o conteúdo
  do filtro, reduzindo custo e latência sem relaxar a validação.
- Rankings sem entidade específica não recebem filtros artificiais.
- Alias novos precisam ser aprovados explicitamente no extrator local.
- Perguntas com entidades livres não estruturadas continuam aceitas quando o valor planejado
  aparece literalmente na pergunta; um catálogo local poderá ampliar a resolução sem mudar o
  contrato do validator.
- Uma pergunta inválida pode consumir chamadas adicionais, sempre dentro dos limites
  configurados.

## Verificação

Testes cobrem os quatro casos originais, paráfrases, placeholders, literais truncados, múltiplos
valores com `in`, aliases aprovados, palavras gramaticais que não são entidades, associação ao
campo errado, projeção determinística, recuperação após feedback, esgotamento exato do
orçamento, configuração do runtime, exposição opt-in do plano e métricas por capacidade. O
batch mantém as 50 perguntas como regressão end-to-end.

Na execução pós-mitigação de 17 de julho de 2026, as 50 perguntas passaram na primeira
tentativa de avaliação (`50/50`), com média de `9,14 s`, p95 de `12,34 s` e limite inferior
de `92,86%` no intervalo de Wilson de 95%. Esse resultado é uma amostra da etapa não
determinística, não uma garantia de acerto futuro; por isso o relatório preserva tentativas e
o runner aceita múltiplos trials.

## Decisões relacionadas

- [Validação determinística de datas com reparo limitado do plano](./validacao-deterministica-de-datas-com-reparo-limitado.md)
- [Implementações substituíveis para as etapas não determinísticas](./abstracao-das-etapas-nao-deterministicas.md)
- [Álgebra limitada para insights de vendas em linguagem natural](./consultando-db-com-linguagem-natural.md)
- [Comparação de vendas com agregação condicional e cursor](./comparacao-de-vendas-com-agregacao-condicional-e-cursor.md)
