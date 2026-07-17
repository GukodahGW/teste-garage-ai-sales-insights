# Álgebra analítica tipada para sales insights

## Status

Aceita. Substitui o catálogo de duas operações descrito em
[Catálogo fundamental para insights de vendas](./consultando-db-com-linguagem-natural.md).

## Contexto

Operações específicas como `sales.calculate` e `sales.top_products` evitavam que o modelo
somasse valores, mas não representavam agrupamentos relacionais, comparações, janelas,
coortes ou cestas. Adicionar uma intent para cada nova pergunta faria o catálogo crescer de
forma combinatória.

O modelo transacional anterior também confundia o grão de pedido com o grão de item. Essa
estrutura não permitia contar pedidos distintos, calcular ticket médio de pedidos com vários
itens ou identificar produtos comprados juntos.

## Decisão

O planner pode produzir um programa limitado a cinco nós de uma álgebra fechada:

- `sales.aggregate`: múltiplas métricas e dimensões, filtros, `having`, ordenação, totais e
  janelas de rank, participação, acumulado e média móvel;
- `sales.compare`: valores atual/base, diferença e variação percentual;
- `sales.basket`: frequência, suporte, confiança e lift de pares no mesmo pedido;
- `sales.cohort`: retenção, clientes ativos e receita por coorte;
- `sales.forecast`: tendência linear reproduzível, intervalo e erro de backtest;
- `sales.anomalies`: detecção reproduzível por desvio padrão.

Por compatibilidade, o parser ainda aceita `sales.calculate` e `sales.top_products`. Essas
operações usam o executor legado, não podem compor planos com outras operações e não são a
interface recomendada para novas capacidades.

O modelo escolhe apenas símbolos do vocabulário de negócio. Ele não escolhe tabelas, joins,
SQL, fórmulas ou valores. Períodos são intervalos semiabertos (`start <= t < end`).

### Validação e reparo do planejamento

A saída do modelo passa por duas validações antes de alcançar o executor. O parser valida a
estrutura e o vocabulário fechado; os construtores do domínio validam relações entre campos,
como grão da métrica, granularidade temporal, períodos obrigatórios, filtros, ordenações e
janelas. Um objeto que viole essas relações não pode compor um `SalesQueryPlan`.

O adaptador tolera referências temporais que alguns modelos repetem em `filters`, como
`year=2025`, somente quando elas coincidem exatamente com o intervalo declarado para o ano.
Nesse caso, a referência é normalizada para o `TimePeriod` e nunca se transforma em um
`SalesFilter`. Referências temporais incompletas, conflitantes ou com operador incompatível
são recusadas.

Quando a primeira saída é inválida, `LangChainSalesQueryPlanner` envia o diagnóstico de
validação ao modelo. No runtime, o padrão permite uma única tentativa de reparo do plano
completo; a configuração é limitada a no máximo três tentativas totais para controlar custo
e latência. Se nenhuma tentativa resultar em um plano válido, o planner lança
`SalesPlanningError`; o adaptador HTTP responde `422`, sem executar uma consulta parcial e
sem expor a falha como erro interno `500`.

### Camada semântica

Cada tipo de métrica é mapeado pela camada semântica para um grão e uma fórmula controlados.
Receita e ticket sem dimensão/filtro de produto usam `orders`; unidades e dimensões ou
filtros de produto/categoria usam `order_items`. Contagens de pedido usam
`COUNT(DISTINCT order_id)`. Como ticket médio é uma métrica de pedido, sua combinação com
produto/categoria é recusada até existir uma regra explícita de atribuição. O adaptador
também rejeita moedas misturadas quando a consulta monetária não contém filtro ou dimensão
de moeda.

`revenue` representa o valor líquido de descontos antes de estornos. `net_revenue` subtrai
estornos no grão do pedido; no grão de item, somente estornos vinculados ao item podem ser
atribuídos e a resposta inclui um aviso sobre estornos sem item. `refund_amount` segue a
mesma regra de atribuição.

Produtos e categorias priorizam os snapshots gravados no item e usam o cadastro atual como
fallback quando o snapshot estiver ausente. Filtros singulares de produto, categoria ou
cliente que correspondam a mais de uma entidade resultam em status `ambiguous`, e não em
uma escolha silenciosa.

### Modelo transacional

O esquema passa a possuir `orders`, `order_items`, `refunds` e `categories`. A tabela
`sales` permanece temporariamente como contrato legado. A migração cria um pedido de um item
para cada venda existente e preserva os totais. Ela não inventa cestas históricas: uma venda
legada continua sendo um pedido de item único.

O ponto de composição do runtime aplica as migrações pendentes antes de construir a
persistência. Uma falha de migração impede a criação da aplicação; assim, uma API configurada
não começa a atender com um schema incompatível com a álgebra.

### Fronteira de confiança

O banco executa joins e agregações. Transformações posteriores recebem somente resultados
agregados. Forecast e anomalias são calculados por código determinístico. O sintetizador
apenas formata `AnalysisDataset`; nenhuma linha de venda ou valor é enviado ao LLM para
cálculo.

## Invariantes

- métricas aditivas de item, como `revenue`, preservam o total quando agrupadas por categoria;
- joins de itens não multiplicam métricas de pedido;
- ticket médio usa pedidos distintos e é recusado em dimensões de item sem regra de atribuição;
- baseline zero produz variação percentual indefinida, nunca infinita;
- top-N por grupo usa dense rank, preserva empates e possui ordenação estável;
- cestas exigem itens pertencentes ao mesmo `order_id`;
- perguntas causais não são convertidas em causalidade aparente;
- previsão exige ao menos três períodos observados, é identificada como estimativa e inclui
  intervalo e erro de backtest;
- planos, filtros e cardinalidade possuem limites antes da execução.
- filtros temporais redundantes só são descartados quando equivalem exatamente ao período;
- planos estrutural ou semanticamente inválidos nunca são enviados ao executor;
- comparação, coorte, previsão e anomalias exigem períodos fechados;
- janelas só podem particionar dimensões selecionadas, e acumulados ou médias móveis exigem
  uma única dimensão temporal;
- o runtime não atende requisições antes de aplicar a revisão de schema necessária.

## Consequências

A implementação possui mais contratos e código de compilação, porém a superfície
probabilística continua pequena. Novas formulações de perguntas reutilizam métricas,
dimensões e transformações existentes em vez de criar uma nova intent ou entregar SQL ao
modelo.
