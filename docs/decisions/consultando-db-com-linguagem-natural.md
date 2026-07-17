# Interpretação de consultas em linguagem natural

## Decisão

A aplicação utilizará inicialmente o Gemma 4B para transformar perguntas sobre vendas em um plano estruturado de consulta.

O modelo será responsável apenas por interpretar a linguagem do usuário. Ele não terá acesso direto ao banco de dados e não produzirá SQL para execução.

## Motivação de curto prazo

O uso do Gemma 4B reduz o esforço inicial necessário para lidar com diferentes maneiras de formular uma mesma pergunta.

Isso permite:

* validar rapidamente a experiência proposta;
* descobrir quais perguntas os usuários realmente fazem;
* identificar ambiguidades e operações recorrentes;
* evitar a construção antecipada de uma gramática extensa.

O custo dessa escolha é um maior consumo de memória, processamento e tempo de resposta.

## Possível evolução

Como o domínio de consultas é limitado a vendas, clientes e produtos, uma parte significativa das interpretações poderá futuramente ser realizada por um parser semântico especializado.

Esse parser poderá combinar:

* normalização de termos;
* identificação de intenções;
* extração de datas, valores e entidades;
* regras de domínio;
* classificação textual leve.

Essa solução exigirá maior investimento de desenvolvimento e manutenção, mas poderá reduzir consideravelmente o custo computacional em longo prazo.

## Implementação plugável

A camada de aplicação não dependerá diretamente do Gemma.

Será definido um contrato comum:

```python
from typing import Protocol

class QueryInterpreter(Protocol):
    async def interpret(self, question: str) -> QueryPlan:
        ...
```

Diferentes implementações poderão atender ao mesmo contrato:

```text
GemmaQueryInterpreter
SemanticParserQueryInterpreter
HybridQueryInterpreter
```

O fluxo permanecerá o mesmo:

```text
Pergunta
   ↓
QueryInterpreter
   ↓
QueryPlan validado
   ↓
Dispatcher
   ↓
Repositories
   ↓
SQLAlchemy
```

Dessa forma, o Gemma poderá ser substituído, complementado ou utilizado apenas como fallback sem alterar os repositories ou as regras de execução.

## Estratégia de longo prazo

As perguntas recebidas e os planos aprovados poderão ser armazenados como exemplos de domínio.

Com esses dados, será possível implementar progressivamente um parser semântico para as consultas mais frequentes:

```text
Parser semântico
   ↓
Interpretação confiável?
   ├── Sim → executar o plano
   └── Não → utilizar o Gemma
```

Essa abordagem preserva a flexibilidade linguística inicial e permite reduzir gradualmente o custo de inferência.
