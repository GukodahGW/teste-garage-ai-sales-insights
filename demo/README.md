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
