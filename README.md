# Tutorial de execução

## Pré-requisitos

- Python 3.11 ou superior.
- Acesso à internet.
- `.env` e `cloudflare-api-key.txt` na raiz.
- Provider `https://gemma.lontra-agil.online/v1` disponível.
- Todos os comandos executados na raiz do repositório.

## Windows — PowerShell

### Terminal 1: instalação e API

Antes de repetir o bootstrap no Windows, encerre qualquer instância de
`garage-sales-api.exe`. O sistema operacional mantém esse entrypoint bloqueado enquanto a
API está em execução e impede a reinstalação editável do pacote.

```powershell
cd C:\caminho\teste-garage-ai-sales-insights

py -3 scripts/bootstrap.py --dev

py -3 scripts/run.py init-db
py -3 scripts/run.py check-db
py -3 scripts/run.py list-sales

py -3 scripts/verify.py

.\.venv\Scripts\garage-sales-api.exe
```

A última instrução mantém o terminal ocupado executando a API.
Ao criar o runtime, a API aplica as migrações pendentes antes de começar a atender.

### Terminal 2: demos

```powershell
cd C:\caminho\teste-garage-ai-sales-insights

python.exe demo\top_products.py

python.exe demo\sales_insights.py `
  "Qual foi o total de vendas do ano de 2025"
```

## Linux e macOS

### Terminal 1: instalação e API

```bash
cd /caminho/teste-garage-ai-sales-insights

python3 scripts/bootstrap.py --dev

python3 scripts/run.py init-db
python3 scripts/run.py check-db
python3 scripts/run.py list-sales

python3 scripts/verify.py

./.venv/bin/garage-sales-api
```

### Terminal 2: demos

```bash
cd /caminho/teste-garage-ai-sales-insights

python demo/top_products.py

python demo/sales_insights.py \
  "Qual foi o total de vendas do ano de 2025"
```

O resultado deve ter status HTTP `200`, conter `R$ 2.309,78` e pode incluir o dataset
analítico estruturado. Um trecho representativo da resposta é:

```json
{
  "answer": "Resultado: ano=2025: receita=R$ 2.309,78.",
  "data": [
    {
      "rows": [
        {
          "dimensions": [{"name": "year", "value": "2025"}],
          "metrics": [{"name": "revenue", "value": "2309.78"}]
        }
      ]
    }
  ]
}
```
