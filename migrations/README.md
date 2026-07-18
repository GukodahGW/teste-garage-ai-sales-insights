# Database migrations

As revisoes deste diretorio sao a fonte de verdade para o schema relacional.

Execute `python scripts/migrate.py` para aplicar todas as revisoes pendentes ao banco
definido por `GARAGE_DATABASE_URL`. Novas alteracoes estruturais devem ser adicionadas como
novas revisoes Alembic; revisoes ja aplicadas nao devem ser editadas.

As migracoes alteram somente o schema. O dataset de referencia e uma operacao separada,
executada explicitamente com `python scripts/seed.py` depois das migracoes.
