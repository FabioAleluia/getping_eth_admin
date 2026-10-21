# Correções de código para produção — 21/10/2026

Implementação dos oito itens do grupo **1. Correções no código** da revisão de produção. As configurações e validações da VPS continuam sendo etapas independentes.

| Item | Alteração |
|---|---|
| Zero agentes | O formulário usa o valor padrão somente quando o campo está ausente ou nulo; zero permanece zero ao editar e salvar. |
| Colisão entre login/e-mail | Namespace compartilhado entre contas, com verificações nas operações administrativas e índices/triggers no banco. Login ambíguo é recusado sem escolher uma conta. |
| Normalização | Função central remove espaços das extremidades e converte para minúsculas em cadastro, edição, perfil, login e CLI. A migração normaliza contas existentes após verificar conflitos. |
| Tipos inválidos | API valida que os limites armazenados são inteiros e estão na faixa permitida, retornando JSON 503 em inconsistência. |
| Validação no banco | Migração 003 substitui os triggers de licença por validação de tipo e faixa; zero agentes continua permitido. |
| Diagnóstico | `security-check` incorpora a validação comercial e de identidades, além de comparar versões, tabelas/colunas obrigatórias e definições de índices/triggers com a distribuição. |
| Exclusão inexistente | Retorna 404 sem evento de exclusão. A verificação e a operação ocorrem sob uma transação de escrita, evitando concorrência entre a consulta e a exclusão. |
| Regressões | Testes adicionais de formulários, autenticação, CLI, concorrência, dados legados, migração e drift de schema. |

## Atualização obrigatória do banco

A versão exige **003_production_validation.sql**, além das migrações anteriores. A migração não foi executada no banco operacional durante o desenvolvimento.

Com o serviço parado e o mesmo ambiente da instalação, preserve código/configuração anteriores e um backup consistente. Ensaie primeiro em uma cópia do banco:

```bash
venv/bin/flask --app getping_admin:create_app backup-db /CAMINHO-SEGURO/backup-antes-003.db
venv/bin/flask --app getping_admin:create_app check-data
venv/bin/flask --app getping_admin:create_app init-db
venv/bin/flask --app getping_admin:create_app check-data
venv/bin/flask --app getping_admin:create_app security-check
```

Use caminhos reais e confira `GETPING_DATABASE` antes de executar. Não gere outra `SECRET_KEY` para atualizar.

Se houver identificadores vazios ou pertencentes a contas diferentes após normalização, `init-db` interrompe a migração 003 e informa os IDs para revisão. Não mescla contas, não escolhe um proprietário e não deixa a normalização parcialmente aplicada. Faça a revisão na cópia, defina quais identificadores cada conta deve usar e repita o ensaio antes da atualização real.

Contas existentes sem conflito têm username/e-mail normalizados. IDs, hashes, papéis e versões de autenticação são preservados pelo código de normalização. Limites comerciais legados não são convertidos nem substituídos automaticamente: `check-data` os aponta para revisão. A nova validação também pode impedir alterações em uma licença inconsistente até que os campos sejam corrigidos.

## Contratos dos diagnósticos

- `/health`: verifica prontidão da estrutura e versões, incluindo índices e triggers esperados. Retorna 503 diante de drift; não faz uma varredura dos dados comerciais a cada chamada.
- `check-data`: verifica limites/datas das licenças e conflitos/valores vazios nos identificadores; não modifica registros.
- `security-check`: verifica integridade/referências, estrutura esperada, dados e configuração. Inconsistência estrutural ou de dados retorna erro mesmo sem `--strict`.
- `security-check --strict`: além dessas falhas, retorna erro para recomendações de configuração pendentes, como HTTPS e transição de vínculos.

Os diagnósticos não reparam automaticamente uma migração registrada com objetos ausentes ou alterados. Investigue e recupere a estrutura de forma explícita em cópia/backup; repetir `init-db` não deve ser usado como promessa de reparo de drift. Formatação equivalente de SQL pode exigir revisão se divergir da definição distribuída.

## Validação

- **122 testes passaram** em 25,944 s, com `ResourceWarning` tratado como erro; são 20 testes novos de regressão.
- Ruff 0.17.1: lint aprovado e todos os 52 arquivos Python formatados conforme a configuração do projeto.
- `git diff --check` aprovado.
- Wheel construído a partir de cópia do código em `/tmp`, instalado em outro diretório temporário e executado fora do repositório com `python -I`. O script de verificação confirmou templates, CSS, JavaScript, schema, migrações, CLI e API, incluindo readiness com a migração 003. Foram reutilizadas as dependências já instaladas no venv para essa verificação.
- Ferramentas de lint/build instaladas somente em `/tmp`; o ambiente virtual operacional não foi modificado.

Todos os ensaios usam bancos temporários; nenhuma configuração de VPS ou migração do banco operacional foi aplicada por estas correções.
