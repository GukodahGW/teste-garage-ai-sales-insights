# Abstração da persistência relacional por meio de repositories

## Status

Aceita, com a extensão descrita em
[Álgebra analítica tipada para sales insights](./algebra-analitica-de-vendas.md).

## Contexto

A aplicação consulta dados relacionais de vendas, clientes e produtos em dois tipos de
fluxo:

- fluxos determinísticos, nos quais o próprio caso de uso define os filtros, a ordem e o
  tratamento dos dados;
- fluxos com planejamento não determinístico, nos quais um modelo interpreta uma pergunta
  em linguagem natural e componentes determinísticos executam e apresentam a resposta.

Esses fluxos precisam acessar os mesmos dados sem depender de SQLAlchemy, de SQL escrito
manualmente, do dialeto do banco ou de detalhes como sessão, transação e modelos ORM.
Também não é aceitável permitir que uma implementação não determinística produza ou
execute consultas arbitrárias. Além de aumentar o acoplamento, isso tornaria o conjunto de
operações possíveis difícil de validar, testar e observar.

O SQLAlchemy abstrai parte das diferenças entre bancos relacionais, mas continua sendo uma
decisão de infraestrutura. Se suas sessões, expressões ou modelos forem expostos aos casos
de uso, a tecnologia de persistência passa a determinar a forma da aplicação e se espalha
por componentes que deveriam representar comportamentos do negócio.

## Direcionadores da decisão

- manter as regras de negócio independentes da tecnologia de persistência;
- limitar o acesso a dados a operações explícitas, validadas e conhecidas;
- usar a mesma fronteira de dados nos comportamentos determinísticos e não determinísticos;
- permitir a troca independente do banco, do ORM e dos provedores de IA;
- tornar os casos de uso testáveis sem banco real ou modelo de linguagem;
- concentrar otimizações e particularidades de cada banco na infraestrutura.

## Decisão

Definiremos portas de repository orientadas ao domínio, independentes da tecnologia que as
implementa. Os casos de uso dependerão somente dessas portas e dos modelos internos de
domínio/aplicação. SQLAlchemy será um adaptador de saída, e não a API de persistência da
aplicação.

As portas oferecem apenas operações necessárias aos comportamentos atuais. Por exemplo,
`SaleReadRepository`, `CustomerReadRepository` e `ProductReadRepository` expõem
`get_by_id` e `find` com critérios tipados. `SalesAnalyticsRepository` recebe somente a
álgebra tipada. `RelationalPersistence`, `RelationalReadUnitOfWork` e sua extensão
`RelationalAnalyticsReadUnitOfWork` agrupam essas portas e delimitam o ciclo de vida da
leitura. Sessões, consultas, modelos ORM e diferenças entre SQLite, PostgreSQL ou MySQL
permanecem no adaptador de infraestrutura.

Não criaremos um repository genérico que apenas reproduza a API do ORM. Quando um novo
comportamento exigir acesso adicional, a operação deverá ser modelada explicitamente na
porta apropriada, com entradas, saídas e limites coerentes com o domínio.

## Fronteira entre etapas determinísticas e não determinísticas

O caso de uso é o orquestrador e a fronteira de confiança. Ele não entrega uma sessão, um
objeto de consulta ou acesso irrestrito aos repositories para o modelo de linguagem.

No fluxo de sales insights, a etapa não determinística de planejamento só pode produzir um
`SalesQueryPlan` tipado e limitado. A implementação atual aceita a álgebra fechada de
agregação, comparação, cesta, coorte, previsão e anomalias. A implementação SQLAlchemy de
`SalesAnalyticsRepository` compila esses símbolos para
operações do banco; o planner não recebe sessão, metadados relacionais ou SQL. O
sintetizador determinístico recebe somente `AnalysisDataset` já calculado.

```text
Pergunta
   |
   v
Planner não determinístico
   |
   v
SalesQueryPlan (zero a cinco operações tipadas)
   |
   v
Executor determinístico -> SalesAnalyticsRepository
                                  |-> agregações/joins no banco
                                  +-> transformações sobre resultados agregados
   |
   v
SalesQueryEvidence
   |
   v
Sintetizador determinístico -> resposta
```

Nos casos de uso totalmente determinísticos, como o endpoint legado de produtos mais
vendidos, a aplicação usa os repositories de leitura na mesma unidade de trabalho. Os dois
tipos de comportamento compartilham a fronteira de persistência, embora o fluxo analítico
use a porta especializada `SalesAnalyticsRepository`.

Essa separação também permite trocar apenas o planner, o sintetizador ou o executor
determinístico. Nenhuma dessas substituições exige alterar os contratos de persistência
enquanto as necessidades de dados do comportamento permanecerem as mesmas.

## Por que esta decisão é crucial para manutenção e extensão

A direção das dependências fica estável: os detalhes tecnológicos dependem dos contratos do
domínio, e não o contrário. Uma mudança de driver, ORM ou banco tende a ficar restrita ao
adaptador; uma mudança no provedor de IA tende a ficar restrita ao planner ou ao
sintetizador; e uma mudança de regra de negócio tende a ficar restrita ao caso de uso. Isso
reduz o número de componentes afetados por cada alteração e evita que decisões independentes
sejam modificadas em conjunto.

As operações predefinidas formam uma linguagem pequena e controlada de acesso aos dados.
Essa linguagem funciona como um ponto explícito de evolução: novos filtros e consultas são
adicionados conscientemente, podem receber validação, limites de cardinalidade e custo,
autorização, telemetria e testes de contrato. A paginação permanece aplicável aos
repositories legados; consultas analíticas agregam no banco e limitam resultados. O sistema
pode crescer sem abrir caminhos paralelos e não auditáveis até o banco.

A mesma fronteira melhora os testes. Um caso de uso pode receber fakes dos repositories,
um executor pode ser testado com planos fixos e um planner não determinístico pode ser
testado apenas quanto à produção de operações válidas. Falhas passam a ser localizadas com
mais facilidade porque planejamento, execução de dados e síntese têm responsabilidades e
contratos distintos.

## Consequências positivas

- Casos de uso e entidades permanecem independentes de ORM, driver e banco específicos.
- SQLite, PostgreSQL, MySQL ou outra tecnologia relacional podem ser suportados por novos
  adaptadores sem reescrever as regras de negócio.
- Provedores de IA não executam SQL nem escolhem operações fora do vocabulário autorizado.
- Validação, limites, autorização, observabilidade e políticas de desempenho podem ser
  aplicados em pontos conhecidos.
- Implementações em memória e fakes tornam os testes rápidos e determinísticos.
- Fluxos determinísticos e não determinísticos reutilizam a mesma semântica de acesso aos
  dados.
- Novos casos de uso podem combinar operações existentes sem conhecer a infraestrutura.

## Custos e riscos aceitos

- Haverá código adicional para portas, critérios, mapeamentos e adaptadores.
- Uma nova necessidade de consulta pode exigir a evolução coordenada do contrato e de suas
  implementações.
- Uma abstração inadequada pode esconder recursos importantes do banco ou gerar consultas
  ineficientes; por isso, os contratos devem expressar necessidades do domínio, e não buscar
  uma independência tecnológica absoluta.
- Testes de contrato serão necessários para garantir comportamento equivalente entre
  diferentes implementações dos repositories.

Esses custos são aceitos porque ficam concentrados e explícitos. Eles são menores do que o
custo recorrente de alterar regras de negócio, integrações de IA e detalhes de persistência
que estejam acoplados entre si.

## Alternativas rejeitadas

### Usar SQLAlchemy diretamente nos casos de uso

Rejeitada porque espalha sessões, modelos ORM e expressões de consulta pela aplicação,
dificulta testes isolados e faz mudanças de persistência atravessarem as regras de negócio.

### Permitir que o modelo gere e execute SQL

Rejeitada porque transforma uma saída não determinística em acesso irrestrito à
persistência. A abordagem dificulta validação, autorização, controle de custo, portabilidade
entre dialetos e reprodução de falhas.

### Criar um repository CRUD genérico

Rejeitada porque apenas desloca o acoplamento ao mecanismo de persistência para outra API.
Operações genéricas demais permitem combinações que o domínio não precisa e não deixam
claras as consultas efetivamente suportadas.

## Regra de evolução

Uma nova operação de dados só deve ser adicionada quando exigida por um comportamento da
aplicação. Ela deve ser representada por um contrato tipado, ter limites e validações
explícitos, possuir testes de contrato e ser implementada pelo adaptador de persistência sem
expor detalhes tecnológicos ao caso de uso ou às etapas não determinísticas.
