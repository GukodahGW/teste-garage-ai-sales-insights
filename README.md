# Garage AI Sales Insights

Camada de consultas plugavel com contratos de dominio e SQLAlchemy. O runtime local e
sempre executado pela `.venv` deste repositorio.

## Preparacao em outro computador

Pre-requisito: Python 3.11 ou superior e acesso à internet na primeira instalacao. Nao e
necessario instalar SQLAlchemy, pytest ou qualquer outra dependencia globalmente.

Windows:

```powershell
py -3 scripts/bootstrap.py
py -3 scripts/run.py init-db
py -3 scripts/run.py check-db
```

Linux ou macOS:

```bash
python3 scripts/bootstrap.py
python3 scripts/run.py init-db
python3 scripts/run.py check-db
```

O primeiro comando cria `.venv`, instala as versoes fixadas em `requirements/` e instala
este projeto dentro dela. `run.py` sempre usa o Python dessa `.venv`; nao e preciso
ativa-la manualmente.

Para recriar o ambiente do zero:

```text
python scripts/bootstrap.py --recreate
```

O diretorio `.venv` nao deve ser versionado: ele contem binarios diferentes para Windows,
Linux e macOS. O que deve estar no repositorio sao o bootstrap e os arquivos `.lock` que
permitem reproduzi-lo.

## Execucao

```text
python scripts/run.py check-db
python scripts/run.py init-db
python scripts/run.py list-sales
python scripts/run.py list-sales --customer-id 3 --min-total 100.00
```

`init-db` serve para desenvolvimento e prototipos. Em producao, use migracoes Alembic.

## Desenvolvimento

```text
python scripts/bootstrap.py --dev
python scripts/verify.py
```

`verify.py` executa testes, Ruff e Mypy com as ferramentas da `.venv`.

## Banco de dados

SQLite e o padrao e nao exige driver adicional. Para preparar outro driver:

```text
python scripts/bootstrap.py --database postgres
python scripts/bootstrap.py --database mysql
```

Configure a conexao pela variavel `GARAGE_DATABASE_URL`:

```text
SQLite:     sqlite+pysqlite:///./garage.db
PostgreSQL: postgresql+psycopg://usuario:senha@localhost/garage
MySQL:      mysql+pymysql://usuario:senha@localhost/garage
```

PowerShell:

```powershell
$env:GARAGE_DATABASE_URL = "postgresql+psycopg://usuario:senha@localhost/garage"
py -3 scripts/run.py check-db
```

Bash:

```bash
export GARAGE_DATABASE_URL="postgresql+psycopg://usuario:senha@localhost/garage"
python3 scripts/run.py check-db
```

As variaveis aceitas estao documentadas em `runtime.env.example`. Esse arquivo e somente
um modelo; credenciais reais nao devem ser versionadas.

## Arquitetura

```text
application/queries.py
         |
         v
domain/ports.py  <---- contrato implementado por qualquer adaptador
         ^
         |
infrastructure/sqlalchemy/ ----> SQLite | PostgreSQL | MySQL
```

- `domain/`: entidades, criterios e contratos sem dependencia de SQLAlchemy.
- `application/`: operacoes como `get_sale_by_id` e `get_sales_by`.
- `infrastructure/sqlalchemy/`: modelos ORM, consultas e controle de sessao.
- `requirements/`: versoes exatas de runtime, desenvolvimento e drivers.
- `scripts/`: preparacao, execucao e verificacao do ambiente.

Uma persistencia diferente pode ser conectada implementando `StructuredPersistence` e
devolvendo uma unidade de trabalho com os mesmos repositorios.

