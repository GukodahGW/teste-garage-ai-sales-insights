# Como executar o projeto

Este tutorial prepara o ambiente local, aplica o schema, carrega o dataset de exemplo e
inicia a API em `http://127.0.0.1:8000`.

## Pré-requisitos

- Python 3.11 ou superior.
- `uv` instalado e disponível no `PATH`.
- Acesso à internet para instalar as dependências e acessar o provider de LLM.
- Um arquivo `.env` na raiz, baseado em `runtime.env.example`.
- A credencial do provider configurada por `GARAGE_LLM_API_KEY` ou
  `GARAGE_LLM_API_KEY_FILE`.
- Todos os comandos executados na raiz do repositório.

O banco padrão é SQLite e será criado como `garage.db`. Para usar PostgreSQL ou MySQL,
ajuste `GARAGE_DATABASE_URL` no `.env` e informe `--database postgres` ou
`--database mysql` durante o bootstrap.

As dependências são declaradas em `pyproject.toml` e resolvidas em `uv.lock`. O bootstrap
usa `uv sync --locked`; se as dependências forem alteradas, atualize o lock
deliberadamente com `uv lock`.

## Windows — PowerShell

### 1. Preparar o ambiente

```powershell
cd C:\caminho\teste-garage-ai-sales-insights
py -3 scripts/bootstrap.py --dev
```

Antes de repetir o bootstrap, encerre qualquer instância de `garage-sales-api.exe`. O
Windows mantém esse arquivo bloqueado enquanto a API está em execução.

### 2. Preparar o banco de dados

Migração e seed são processos separados e precisam ser executados explicitamente:

```powershell
py -3 scripts/migrate.py
py -3 scripts/seed.py
```

O migrador altera somente o schema. O seed carrega o dataset de referência e pode ser
executado novamente sem duplicar os registros.

### 3. Verificar a instalação

```powershell
py -3 scripts/run.py check-db
py -3 scripts/run.py list-sales
py -3 scripts/verify.py
```

O último comando executa os testes, o linter e a verificação de tipos.

### 4. Iniciar a API

```powershell
.\.venv\Scripts\garage-sales-api.exe
```

Esse processo permanece em primeiro plano. A API não executa migrações nem seeds ao
iniciar; qualquer alteração de schema ou carga de dados deve usar os scripts da etapa 2.

### 5. Executar os exemplos

Com a API ativa, abra outro PowerShell na raiz do projeto:

```powershell
.\.venv\Scripts\python.exe demo\top_products.py

.\.venv\Scripts\python.exe demo\sales_insights.py `
  "Qual foi o total de vendas do ano de 2025"
```

## Linux e macOS

### 1. Preparar o ambiente

```bash
cd /caminho/teste-garage-ai-sales-insights
python3 scripts/bootstrap.py --dev
```

### 2. Preparar o banco de dados

```bash
python3 scripts/migrate.py
python3 scripts/seed.py
```

Migração e seed são processos explícitos e independentes. O migrador altera somente
o schema, e o seed pode ser repetido sem duplicar os registros de referência.

### 3. Verificar a instalação

```bash
python3 scripts/run.py check-db
python3 scripts/run.py list-sales
python3 scripts/verify.py
```

### 4. Iniciar a API

```bash
./.venv/bin/garage-sales-api
```

Esse processo permanece em primeiro plano. A API não modifica o schema nem carrega dados
durante a inicialização.

### 5. Executar os exemplos

Com a API ativa, abra outro terminal na raiz do projeto:

```bash
./.venv/bin/python demo/top_products.py

./.venv/bin/python demo/sales_insights.py \
  "Qual foi o total de vendas do ano de 2025"
```

## Resultado esperado

Os exemplos devem receber status HTTP `200`. Para a pergunta sobre o total de vendas de
2025, a resposta esperada é:

```json
{
  "answer": "O total de vendas em 2025 foi de R$ 2.309,78."
}
```

Consulte `demo/README.md` para outros exemplos de agrupamento, ranking, comparação e
paginação.

## Testar a eficácia do `GetSalesInsightsUseCase`

O planejamento das consultas usa uma LLM e, portanto, pode produzir planos diferentes para a
mesma pergunta. A eficácia do use case não deve ser avaliada apenas verificando se ele respondeu
sem lançar erro: a resposta precisa conter os valores que seriam obtidos por um cálculo
determinístico sobre as vendas armazenadas.

O runner recomendado executa diretamente o `GetSalesInsightsUseCase`; não é necessário iniciar
o Uvicorn. O banco configurado precisa estar populado e o provider da Gemma precisa estar ativo.
Com o ambiente virtual e o `.env` configurados, execute no PowerShell:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_get_sales_insights_efficacy
```

O comando sempre prepara e executa as 50 perguntas. Durante a execução ele imprime um resultado
curto para cada caso:

```text
[01/50] PASSOU annual_revenue (8.42s)
[02/50] PASSOU monthly_sale_count (7.91s)
...
====================================================================
RESULTADO DE EFICÁCIA — GET SALES INSIGHTS
====================================================================
Perguntas corretas: 50/50 (100.00%)
Latência média:     9.14s
Latência p95:       12.34s
```

Ao final, o resumo apresenta:

- quantidade e percentual de respostas corretas;
- intervalo de confiança de Wilson de 95%;
- tempo total, latência média e p95;
- número de capacidades sem falhas;
- perguntas, fatos esperados e capacidades que falharam;
- caminho do relatório JSON detalhado, por padrão
  `.reports/get-sales-insights-efficacy.json`.

### Como a eficácia é calculada

Antes de chamar a LLM, o runner lê as vendas relacionais brutas e calcula em Python todos os
resultados esperados. O oracle não reutiliza o planner, o repositório analítico nem o
sintetizador da aplicação. Isso evita que um erro da implementação avaliada também contamine o
resultado usado como referência.

Cada tentativa passa somente quando todos os fatos esperados aparecem na resposta e permanecem
associados ao grupo correto. Por exemplo, o valor de `Product A` não pode ser encontrado apenas
na linha de `Product E`. As 50 perguntas cobrem totais, tickets médios, séries, rankings
ascendentes e descendentes, filtros por nome/SKU/e-mail, múltiplas métricas, comparações entre
períodos e agrupamentos em até duas dimensões.

Uma execução por pergunta é adequada como regressão rápida. Para medir melhor a variação não
determinística, repita cada pergunta de três a cinco vezes:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_get_sales_insights_efficacy `
  --trials 3 `
  --minimum-pass-rate 0.95 `
  --json-report .reports\get-sales-insights-efficacy-3-trials.json
```

Com `--trials 3`, o runner faz 150 execuções: três para cada uma das 50 perguntas. O código de
saída é `0` quando a taxa alcança `--minimum-pass-rate`, `1` quando fica abaixo dela e `2` para
problemas de configuração ou ausência de dados. O intervalo de Wilson representa a incerteza da
amostra; uma execução com 100% não garante que toda execução futura também acertará.

Essa medição combina eficácia funcional e latência sequencial. Ela não substitui um teste de
carga concorrente do provider ou da API.

### Avaliar também o endpoint HTTP

Para incluir o adapter HTTP e o contrato do endpoint na avaliação, inicie a API e use o runner
de baixo nível:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_sales_insights.py `
  --trials 5 `
  --minimum-pass-rate 0.90 `
  --json-report .reports\sales-insights-http-evaluation.json
```

Esse runner envia as mesmas 50 perguntas para `/sales-insights` com `include_plan=true`. O plano
tipado de cada tentativa é preservado no relatório para facilitar o diagnóstico.

Datas de calendário e filtros semânticos possuem retries independentes e limitados:

```dotenv
GARAGE_PLANNER_DATE_VALIDATION_MAX_RETRIES=2
GARAGE_PLANNER_FILTER_VALIDATION_MAX_RETRIES=2
```

Cada valor aceita de `0` a `5` e representa novas composições depois da primeira rejeição. A
validação de filtros preserva literais como `Category 2`, `Product A`, SKUs e e-mails, rejeita
placeholders como `all`/`todos` e não repete consultas apenas porque retornaram zero linhas.

Para inspecionar ou executar casos HTTP específicos:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_sales_insights.py --list-cases
.\.venv\Scripts\python.exe scripts\evaluate_sales_insights.py `
  --case best_week_by_revenue `
  --case month_over_month_by_category `
  --trials 10
```
