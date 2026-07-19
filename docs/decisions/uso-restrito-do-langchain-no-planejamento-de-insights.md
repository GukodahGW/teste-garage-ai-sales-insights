# Uso restrito do LangChain no planejamento de insights

## Status

Aceita.

## Contexto

`GetSalesInsights` precisa transformar uma pergunta em linguagem natural em um plano
analítico tipado. A aplicação já separa essa etapa não determinística da execução no banco
e da síntese da resposta por meio das portas `SalesQueryPlanner`, `SalesQueryExecutor` e
`SalesInsightSynthesizer`.

O provider público da Gemma expõe uma fila assíncrona de jobs, e não um endpoint síncrono
compatível com o cliente `ChatOpenAI`. Portanto, é necessário explicitar se LangChain é o
cliente do provider, o orquestrador da aplicação ou apenas uma ferramenta interna do
adapter de planejamento.

## Decisão

Manter `langchain-core` somente dentro do adapter de planejamento e do adapter de modelo.
LangChain não atravessa as portas da aplicação e não coordena o caso de uso.

O fluxo atual é:

```text
pergunta
   |
   v
ChatPromptTemplate
   |
   v
GemmaJobChatModel (BaseChatModel)
   |
   +--> POST /v1/jobs
   +--> GET /v1/jobs/{id}/wait
   |
   v
AIMessage
   |
   v
PydanticOutputParser
   |
   v
_QueryPlanOutput --> validações determinísticas --> SalesQueryPlan
```

As responsabilidades ficam distribuídas assim:

| Componente | Uso de LangChain |
| --- | --- |
| `LangChainSalesQueryPlanner` | Compõe mensagens com `ChatPromptTemplate`, encadeia prompt, modelo e parser com `Runnable` e converte a resposta com `PydanticOutputParser`. |
| `GemmaJobChatModel` | Implementa o contrato `BaseChatModel` e converte mensagens e respostas entre os tipos do LangChain e o JSON do provider. |
| Runtime | Recebe um `BaseChatModel` e o injeta no planner durante a composição da aplicação. |
| Testes do planner | Usam `FakeListChatModel` para testar prompts, parsing e reparos sem chamar o provider. |

O protocolo da Gemma é implementado diretamente com `httpx` dentro de
`GemmaJobChatModel`. Esse adapter cria uma chave de idempotência por chamada, submete o
job, faz long polling até um estado terminal, aplica retries de transporte com a mesma
chave e tenta cancelar um job ainda ativo quando o prazo total expira. O projeto não usa
`langchain-openai` nem `ChatOpenAI`.

O planner usa a LLM apenas para produzir zero ou uma operação do catálogo fechado. Depois
do parsing, validações locais verificam datas, dimensões e filtros antes de criar o
`SalesQueryPlan`. Falhas de validação podem gerar novas composições limitadas, mas não
ampliam o catálogo permitido.

## Fora do escopo do LangChain

LangChain não é usado para:

- acessar banco, sessão, ORM, repositories ou SQL;
- executar agregações, comparações, ordenação ou paginação;
- criar, interpretar ou persistir cursores;
- calcular ou sintetizar valores da resposta;
- implementar endpoints HTTP da aplicação;
- decidir retries internos da fila ou da inferência no provider.

Essas responsabilidades permanecem em componentes determinísticos ou em adapters
específicos. Em particular, o caso de uso depende da porta `SalesQueryPlanner`, não de
classes do LangChain.

## Invariantes

- Tipos do LangChain permanecem restritos ao runtime e a `adapters/langchain`.
- A LLM não recebe conexão, SQL, modelos ORM nem linhas de vendas.
- Nenhum plano é executado antes de passar pelo parser tipado e pelas validações locais.
- O adapter do provider preserva a semântica durável e idempotente da API de jobs.
- Trocar LangChain exige apenas outra implementação de `SalesQueryPlanner` e ajustes no
  composition root; domínio, casos de uso e persistência não devem mudar.

## Consequências

- `langchain-core` continua como dependência de produção para composição de prompts,
  contratos de chat, parsing tipado e modelos falsos de teste.
- O projeto mantém controle explícito sobre autenticação, idempotência, polling,
  cancelamento e erros do provider.
- A remoção de `langchain-openai` evita adaptar à força uma API assíncrona a um cliente
  síncrono incompatível.
- Atualizações de `langchain-core` podem exigir ajustes no adapter, mas não se propagam
  para a aplicação ou o domínio.
- LangChain pode ser removido no futuro substituindo prompt, parser e modelo falso por
  implementações locais atrás da mesma porta, sem mudar o contrato do caso de uso.

## Alternativas consideradas

- Usar `ChatOpenAI` contra `POST /v1/chat/completions`: rejeitada porque o provider público
  exige submissão assíncrona em `POST /v1/jobs`.
- Usar agentes ou ferramentas do LangChain para consultar o banco: rejeitada porque
  ampliaria a superfície não determinística e permitiria que o modelo participasse da
  execução de dados.
- Remover todo o LangChain agora: não escolhida porque `ChatPromptTemplate`,
  `PydanticOutputParser`, o contrato `BaseChatModel` e os modelos falsos já fornecem uma
  fronteira pequena e testada. A alternativa continua possível atrás de
  `SalesQueryPlanner`.

## Decisões relacionadas

- [Implementações substituíveis para as etapas não determinísticas](./abstracao-das-etapas-nao-deterministicas.md)
- [Álgebra limitada para insights de vendas em linguagem natural](./consultando-db-com-linguagem-natural.md)
- [Validação determinística de datas com reparo limitado](./validacao-deterministica-de-datas-com-reparo-limitado.md)
- [Validação determinística de filtros com reparo limitado](./validacao-deterministica-de-filtros-com-reparo-limitado.md)
