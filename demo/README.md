# Demonstrativos da API REST

Com a API em execução em `http://127.0.0.1:8000`, rode os exemplos a partir da
raiz do projeto.

## GET /sales-insights

Usando a pergunta padrão:

```text
python demo/sales_insights.py
```

Informando outra pergunta:

```text
python demo/sales_insights.py "Qual foi o total de vendas de ontem?"
```

Exemplos com agrupamento, ranking e comparação:

```text
python demo/sales_insights.py "Qual foi a semana de 2025 que mais vendeu?"
python demo/sales_insights.py "Quais foram os cinco produtos mais vendidos em 2025?"
python demo/sales_insights.py "Compare o faturamento de 2025 com 2024"
```

Comparações sem `limit` retornam até 100 grupos e podem incluir `next_cursor`. Para buscar a
página seguinte, repita exatamente a mesma pergunta:

```text
python demo/sales_insights.py "Compare o faturamento por categoria de 2025 com 2024" --cursor CURSOR_RECEBIDO
```

## GET /top-products

```text
python demo/top_products.py
```

Os scripts mostram a URL requisitada, o status HTTP e o JSON retornado. Para
apontar os exemplos para outra instância, use `--base-url`:

```text
python demo/top_products.py --base-url http://localhost:9000
```

Também é possível definir a variável de ambiente `GARAGE_API_URL`.
