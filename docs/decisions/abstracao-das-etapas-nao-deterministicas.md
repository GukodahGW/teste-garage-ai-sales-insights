# Implementações substituíveis para as etapas não determinísticas

## Status

Aceita e consolidada. Complementada por
[Álgebra analítica tipada para sales insights](./algebra-analitica-de-vendas.md).

A porta do planner continua vigente. A porta de síntese também permanece como fronteira de
aplicação, mas sua implementação no runtime é determinística e não pode recalcular valores.
O modelo é usado somente para traduzir a pergunta para a álgebra fechada; execução,
transformações numéricas e apresentação são determinísticas.

## Contexto

A aplicação utiliza uma etapa não determinística para interpretar perguntas em linguagem
natural. Atualmente, o planner é implementado com um modelo de linguagem e LangChain, mas
essa é uma escolha tecnológica de integração, não uma regra de negócio. A produção da
resposta a partir das evidências é determinística no runtime atual.

Tecnologias de IA evoluem e são substituídas com frequência. Modelos, provedores, SDKs,
bibliotecas de orquestração, formatos de saída, preços, limites, latência e qualidade podem
mudar independentemente dos comportamentos que a aplicação precisa oferecer. Também pode
ser vantajoso substituir uma etapa probabilística por regras determinísticas, um parser
semântico, uma solução híbrida ou uma cadeia com fallback.

Se os casos de uso dependerem diretamente de LangChain, de um SDK de provedor ou de uma API
específica de modelo, cada troca tecnológica atingirá a orquestração da aplicação, os testes
e possivelmente os adaptadores de entrada. Além disso, planejamento e síntese passariam a
evoluir como uma única unidade, embora tenham responsabilidades, entradas e critérios de
qualidade diferentes.

## Direcionadores da decisão

- manter os casos de uso independentes de modelos, provedores, SDKs e frameworks de IA;
- permitir que planejamento e síntese sejam substituídos separadamente;
- preservar as regras de segurança e os limites de acesso a dados em qualquer implementação;
- viabilizar testes determinísticos da orquestração da aplicação;
- permitir evolução gradual para parsers, regras, modelos diferentes ou estratégias híbridas;
- tornar explícito o contrato que uma nova implementação precisa satisfazer;
- concentrar prompts, parsers e particularidades de provedores nos adaptadores de saída.

## Decisão

A camada de aplicação definirá portas orientadas à responsabilidade de cada etapa, sem
representar uma tecnologia específica:

```python
class SalesQueryPlanner(Protocol):
    def plan(self, *, question: str) -> SalesQueryPlan: ...


class SalesInsightSynthesizer(Protocol):
    def synthesize(
        self,
        *,
        question: str,
        evidence: SalesQueryEvidence,
    ) -> str: ...
```

`SalesQueryPlanner` transforma uma pergunta normalizada em um `SalesQueryPlan` tipado e
independente de provedor. `SalesInsightSynthesizer` transforma a pergunta e evidências já
calculadas em texto de resposta. Os modelos de entrada e saída dessas portas pertencem ao
núcleo de domínio/aplicação e não podem carregar tipos de LangChain ou de SDKs externos.

O `GetSalesInsightsUseCase` dependerá somente dessas duas portas e do executor determinístico
de consultas. As implementações concretas serão injetadas no ponto de composição da
aplicação. O caso de uso não instanciará modelos, não selecionará provedores e não conhecerá
prompts, parsers, credenciais, endpoints ou parâmetros de inferência.

```text
                                  +-----------------------------+
                                  | LangChain + modelo atual    |
                                  | parser semântico            |
Pergunta -> SalesQueryPlanner <---| regras ou estratégia híbrida|
                |                 +-----------------------------+
                v
        SalesQueryPlan
                |
                v
       Executor determinístico -> SalesAnalyticsRepository -> banco
                |
                v
       SalesQueryEvidence
                |
                v                 +-----------------------------+
       SalesInsightSynthesizer <--| templates determinísticos   |
                                  | implementação atual         |
                                  +-----------------------------+
                |
                v
             Resposta
```

LangChain é, portanto, um adaptador de saída do planner. `LangChainSalesQueryPlanner`
satisfaz a porta de planejamento e pode usar `BaseChatModel` internamente para variar
modelos compatíveis. A síntese atual é `DeterministicSalesInsightSynthesizer`. Outras
implementações podem substituir essas portas sem alterar o caso de uso, desde que a síntese
preserve literalmente os fatos calculados e nunca realize aritmética ou inferência numérica.

## LLM como compositora de planos sobre um harness determinístico

Esta separação é uma decisão central de segurança e correção, não apenas uma preferência de
implementação. Neste sistema, o *harness* é o conjunto formado pelos contratos tipados, pelo
caso de uso, pelas validações, pelo executor, pelos repositories e pelo sintetizador
determinístico. Ele oferece à LLM um catálogo fechado de capacidades de negócio e mantém a
autoridade exclusiva para validá-las e executá-las.

A LLM atua somente como compositora declarativa. Ela interpreta a linguagem natural e
seleciona capacidades já existentes, com argumentos tipados como métrica, dimensão, filtro,
período, comparação e limite. Sua saída descreve **o que** o usuário pretende executar, mas
não implementa **como** obter o resultado. Mesmo quando escolhe mais de um nó, ela produz um
programa pequeno e limitado da álgebra; não recebe uma linguagem de programação geral nem
acesso arbitrário a ferramentas.

Trabalhos que programas convencionais executam de forma confiável permanecem em código
determinístico: conexões e consultas, joins, filtros, agregações, fórmulas, ordenação,
arredondamento, janelas, previsões estatísticas definidas, detecção de anomalias, aplicação
de migrações, controle de limites e apresentação dos fatos. O mesmo plano e o mesmo estado
do banco devem produzir as mesmas evidências, independentemente do modelo que formulou o
plano.

Essa divisão cria uma fronteira explícita:

```text
linguagem natural
       |
       v
LLM: escolhe capacidades e compõe argumentos
       |
       v
plano tipado, limitado e sem efeitos
       |
       v
harness: valida estrutura + semântica
       |
       v
código determinístico: consulta, calcula e formata
       |
       v
evidência auditável + resposta
```

A LLM não pode ampliar o catálogo por iniciativa própria. Se uma intenção não puder ser
representada pelas capacidades fornecidas, o resultado correto é sinalizar que ela não é
suportada. Uma capacidade nova só se torna utilizável depois de ser implementada como
contrato e código determinístico, receber limites e validações, possuir testes e então ser
exposta ao planner. O prompt documenta capacidades; ele não cria autoridade nem semântica.

### Invariantes dessa fronteira

- a LLM não recebe conexão, sessão, ORM, SQL executável nem acesso direto ao banco;
- a única saída aceita do planejamento é um `SalesQueryPlan` composto por tipos conhecidos;
- validações estruturais e semânticas ocorrem antes de qualquer efeito de execução;
- reparos de saída podem corrigir um plano, mas nunca relaxam as invariantes do harness;
- cálculos, transformações, arredondamentos e efeitos pertencem a código determinístico;
- o sintetizador recebe somente evidências calculadas e não pode alterar seus fatos;
- capacidades ausentes resultam em resposta não suportada, nunca em SQL, fórmula ou dado
  inventado pela LLM;
- uma nova capacidade exige implementação, validação e testes antes de ser anunciada ao
  modelo.

### Por que essa divisão é crítica

Confiar à LLM operações que código comum executa melhor introduziria variabilidade justamente
onde o sistema precisa de exatidão. Totais financeiros, contagens, regras de atribuição e
efeitos sobre infraestrutura precisam ser reproduzíveis e testáveis. Ao restringir a
incerteza à interpretação e composição do plano, o sistema conserva a flexibilidade da
linguagem natural sem transformar o modelo em banco de dados, calculadora ou runtime de
programas.

Essa fronteira também reduz o impacto de prompt injection e de saídas incorretas: texto do
usuário e respostas do modelo não concedem capacidades que o harness não exponha. Planos
inválidos são recusados antes da execução. Logs e evidências permitem reconstruir o que foi
solicitado, qual plano foi aceito e quais resultados o código produziu. Por fim, modelos
podem ser trocados ou avaliados pela qualidade de composição sem alterar fórmulas, acesso a
dados ou garantias de negócio.

## Contrato de substituição

Compatibilidade de assinatura não é suficiente. Toda implementação deverá preservar o
comportamento definido pela porta e pelos modelos da aplicação.

Uma implementação de `SalesQueryPlanner` deverá:

- retornar somente um `SalesQueryPlan` válido;
- usar apenas o catálogo fechado de operações representado pelos tipos da aplicação;
- respeitar limites de quantidade de nós, métricas, dimensões, filtros, janelas e resultados
  definidos nesses tipos;
- nunca retornar SQL, objetos de consulta, chamadas de ferramenta arbitrárias ou tipos do
  provedor;
- tratar a pergunta como dado não confiável e sinalizar a impossibilidade de produzir um
  plano válido.

No adaptador atual, “plano válido” inclui as invariantes cruzadas dos tipos de domínio, não
apenas JSON bem formado. O adapter pode fazer um número pequeno e configurado de tentativas
de reparo, mas só retorna depois que o plano completo passa por essas invariantes. Ao esgotar
as tentativas, ele sinaliza `SalesPlanningError`; não devolve o último plano inválido nem
executa seus nós válidos parcialmente.

Uma implementação de `SalesInsightSynthesizer` deverá:

- produzir a resposta exclusivamente a partir da pergunta e de `SalesQueryEvidence`;
- não acessar diretamente repositories, conexões ou ferramentas externas;
- não recalcular, arredondar novamente ou substituir valores presentes nas evidências;
- não inventar dados ausentes nem apresentar suposições como evidência;
- explicitar quando as evidências forem vazias ou insuficientes;
- devolver somente o conteúdo esperado pelo caso de uso, sem objetos específicos do
  provedor.

Essas garantias devem ser verificadas por testes de contrato reutilizáveis entre
implementações. Avaliações específicas também podem medir qualidade, custo e latência, mas
não substituem as invariantes funcionais e de segurança.

## Por que esta decisão é crucial para manutenção e extensão

A abstração estabiliza o comportamento da aplicação enquanto permite que a tecnologia varie.
Quando um provedor altera sua API, um modelo é descontinuado ou outra solução oferece melhor
custo ou qualidade, a mudança fica concentrada no adaptador e no ponto de composição. A
orquestração, o acesso controlado aos dados e os adaptadores HTTP ou CLI continuam
inalterados.

Planejamento e síntese separados criam dois eixos independentes de evolução. É possível, por
exemplo, adotar um parser determinístico para perguntas recorrentes ou trocar os templates
de apresentação sem modificar o planner. Também é possível implementar fallback,
roteamento, cache, comparação A/B ou migração gradual como adaptadores compostos que
continuam satisfazendo a mesma porta e as invariantes numéricas.

Essa separação reduz o risco de mudanças. Uma nova implementação pode ser exercitada com os
mesmos testes de contrato, comparada com a anterior e ativada no ponto de composição, sem
reescrever o caso de uso. Se o resultado for inadequado, a implementação anterior pode ser
restaurada sem desfazer alterações nas regras de negócio ou na persistência.

A testabilidade também melhora. O caso de uso pode receber planners e synthesizers falsos,
com resultados previsíveis, para que sua orquestração seja testada sem rede, modelo ou
inferência. O adaptador não determinístico do planner pode ser avaliado isoladamente, com
foco na tradução entre a API externa e os contratos internos.

Por fim, a abstração evita dependência estratégica de um fornecedor. A aplicação passa a
depender das capacidades de que necessita — planejar operações e sintetizar evidências — em
vez de depender da interface circunstancial de uma biblioteca ou modelo.

## Consequências positivas

- Modelos, provedores e frameworks podem ser trocados sem modificar os casos de uso.
- Planner e synthesizer podem ser implementados, testados e implantados separadamente.
- Estratégias determinísticas, probabilísticas e híbridas podem implementar o planner; a
  síntese deve continuar determinística quanto aos fatos e números.
- Testes da aplicação não precisam executar inferência nem acessar serviços externos.
- Tipos de SDKs e bibliotecas permanecem restritos aos adaptadores.
- Migrações graduais, fallback e experimentos podem ser implementados sem criar caminhos
  alternativos dentro do caso de uso.
- As regras de acesso a dados continuam válidas independentemente da tecnologia escolhida.

## Custos e riscos aceitos

- Serão necessários adaptadores e mapeamentos entre formatos externos e modelos da aplicação.
- Cada nova implementação deverá satisfazer testes de contrato e avaliações de qualidade.
- Uma abstração excessivamente genérica pode esconder diferenças relevantes entre modelos;
  por isso, as portas representam responsabilidades da aplicação, não todas as capacidades
  possíveis de uma plataforma de IA.
- Funcionalidades exclusivas de um provedor só poderão ser usadas dentro do adaptador ou após
  uma evolução deliberada do contrato.
- Implementações substituíveis podem ter qualidade, latência e custo diferentes mesmo quando
  preservam o contrato funcional; esses atributos precisam ser medidos separadamente.

Esses custos são aceitos porque tornam explícita a integração com componentes voláteis e
impedem que suas mudanças se propaguem pelo núcleo da aplicação.

## Alternativas rejeitadas

### Usar LangChain ou o SDK do provedor diretamente no caso de uso

Rejeitada porque acopla a regra de orquestração a tipos, erros e ciclos de atualização de uma
tecnologia externa. A troca de modelo ou framework exigiria alterações no núcleo da
aplicação.

### Definir apenas uma porta genérica de modelo de linguagem

Rejeitada porque operações como `invoke(prompt)` ou `generate(messages)` ainda fariam os
casos de uso conhecer prompts, parsing e particularidades de inferência. As portas devem
expressar capacidades da aplicação, como planejar consultas e sintetizar evidências.

### Reunir planejamento e síntese em um único agente

Rejeitada como desenho principal porque impede a substituição independente das etapas,
dificulta testar a execução entre elas e tende a ocultar o limite entre decisão
não determinística e acesso determinístico aos dados.

### Criar condicionais de provedor dentro do caso de uso

Rejeitada porque cada nova tecnologia aumentaria a complexidade da regra de negócio e
exigiria que a aplicação conhecesse configurações e comportamentos de infraestrutura.

## Decisões relacionadas

- [Abstração da persistência relacional por meio de repositories](./abstracao-da-persistencia-relacional.md)
- [Álgebra analítica tipada para sales insights](./algebra-analitica-de-vendas.md)
- [Catálogo fundamental substituído](./consultando-db-com-linguagem-natural.md)

## Regra de evolução

Uma nova tecnologia para planejamento ou síntese deverá ser adicionada como adaptador da
porta correspondente e ligada à aplicação pelo ponto de composição. O contrato só deverá
evoluir quando surgir uma nova necessidade do comportamento da aplicação, nunca apenas para
expor uma conveniência ou um tipo específico de fornecedor.

Mudanças no contrato deverão preservar, sempre que possível, a substituição independente das
duas etapas, os modelos internos independentes de provedor e a separação entre decisões
não determinísticas e execução controlada de acesso aos dados.
