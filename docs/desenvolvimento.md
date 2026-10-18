# Desenvolvimento e estrutura

A aplicação usa um pacote regular Python, fábrica Flask e sete Blueprints. Os contratos da API, nomes de endpoints e comandos administrativos foram preservados na reorganização de 17/10/2026.

## Localização das responsabilidades

| Caminho | Responsabilidade |
|---|---|
| `getping_admin/__init__.py` | Factory, registro de hooks, Blueprints, erros e health check |
| `getping_admin/__main__.py` | Execução local com `python -m getping_admin` |
| `getping_admin/config.py` | Configuração por ambiente e overrides da factory |
| `getping_admin/auth.py` | Carregamento do usuário, expiração da sessão e decorador de login |
| `getping_admin/security.py` | CSRF e complexidade da senha |
| `getping_admin/validation.py` | Validadores e decorador explícito dos formulários |
| `getping_admin/licensing.py` | Status efetivo SQL e geração de chaves |
| `getping_admin/audit.py` | Registro de auditoria na transação do chamador |
| `getping_admin/limits.py`, `pagination.py` | Limites de requisição e paginação |
| `getping_admin/commands.py` | Comandos administrativos Flask CLI |
| `getping_admin/database/db.py` | Conexões, commit, rollback e fechamento |
| `getping_admin/database/migrate.py` | Inicialização e migrações explícitas |
| `getping_admin/database/schema.sql`, `migrations/` | SQL versionado, incluído na distribuição |
| `getping_admin/routes/` | Views dos Blueprints por domínio |
| `getping_admin/templates/`, `static/` | Templates e recursos servidos pelo Flask |
| `tests/` | Suíte unittest e suporte com bancos temporários |
| `assets/`, `tailwind.config.js`, `scripts/build-css.sh` | Entrada e build do CSS |
| `deploy/` | Exemplos de implantação; ajustar ao ambiente antes de usar |
| `docs/historico/` | Diagnósticos e correções das etapas anteriores |

## Preparação

Requer Python 3.12 ou posterior. Na raiz do repositório:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e '.[dev]'
```

As dependências diretas estão em `pyproject.toml`. Os arquivos `requirements*.txt` registram as versões resolvidas usadas na implantação. Ao atualizar dependências diretas, atualize também esses arquivos e execute `pip check` e os testes em ambiente limpo. Não é necessário instalar pytest: a suíte usa `unittest`.

Configure as variáveis e siga os comandos de provisionamento do [README](../README.md). Importar o pacote não inicializa banco nem cria contas. `.env.example` é documentação; o carregamento automático de `.env` não foi adicionado.

## Banco e compatibilidade

Para instalações novas, o padrão é `app.instance_path/db_getping.db`, normalmente `instance/db_getping.db` no checkout. O diretório só é criado ao executar `init-db`. Quando o banco legado `database/db_getping.db` existe junto ao checkout, ele continua sendo selecionado. `GETPING_DATABASE` sempre tem precedência; use caminho absoluto na implantação.

Nenhum dado é transferido durante a inicialização da aplicação. Para atualizar uma instalação existente, configure `GETPING_DATABASE` para o banco operacional antes de executar comandos. Se mudar o diretório, faça backup e ajuste as permissões e `ReadWritePaths` dos serviços. Em instalações via wheel, o caminho de instância pode ficar junto ao prefixo Python; prefira configurar um diretório externo com permissão de escrita.

`app.py` permanece como entrada de compatibilidade para `python app.py` e `app:create_app`. O fluxo principal é `python -m getping_admin` ou `flask --app getping_admin:create_app`. Não foram mantidos aliases dos antigos módulos `core`, `routes`, `config` e `database`: imports internos devem usar `getping_admin`.

## Convenções

- Use imports do pacote `getping_admin`; não altere `sys.path` para executar módulos.
- Mantenha nomes dos Blueprints e endpoints existentes ao mover views.
- Use `@login_required` nas views protegidas e `@validate_form` nos formulários POST. Validação específica de negócio continua na operação correspondente.
- Mantenha as mudanças e seus eventos de auditoria na mesma transação. Não use conexão global compartilhada entre requisições.
- Crie arquivos CSS/JS por domínio quando houver estilo ou comportamento real. Não crie placeholders por obrigação. Arquivos pequenos com função real continuam válidos.
- Não edite migração já aplicada. Mudanças de schema exigem nova migração e testes de atualização.
- Não versione dados locais, caches, ambientes virtuais ou artefatos de build.
- Preserve UTC e o contrato externo do cliente GetPing. Regras comerciais e permissões precisam ser validadas no servidor, mesmo quando a interface as apresenta.

## Verificações

```bash
ruff check .
ruff format --check .
python -B -W error::ResourceWarning -m unittest discover -v
python -m pip check
```

A suíte contém os 77 testes anteriores e regressões da configuração e validação explícita dos formulários. O workflow `.github/workflows/checks.yml` executa as verificações e instala um wheel em ambiente separado para conferir templates, assets, schema, migração, CLI e API.

Para alterar o CSS, use o CLI standalone Tailwind 3.4.17:

```bash
sh scripts/build-css.sh /caminho/tailwindcss-3.4.17
```

A configuração busca classes nos caminhos do pacote. A saída compilada fica versionada em `getping_admin/static/css/tailwind.css`, permitindo servir a interface sem compilador no ambiente de execução.

## Distribuição instalável

```bash
python -m pip wheel --no-deps --wheel-dir dist .
python -m venv /tmp/getping-installed
/tmp/getping-installed/bin/pip install dist/getping_admin-*.whl
```

Execute a verificação isolada fora do repositório, passando o caminho absoluto do script:

```bash
cd /tmp
/tmp/getping-installed/bin/python -I /caminho/do/projeto/scripts/check-installed.py
```

O pacote inclui recursos de execução, sem banco operacional nem testes. Para usar Gunicorn, instale `getping-admin[production]` a partir do wheel e configure `GETPING_DATABASE`, `SECRET_KEY` e o proxy conforme o README. O processo deve conseguir escrever no diretório do banco; schema e recursos do pacote podem ficar somente leitura.

Os relatórios em `historico/` descrevem estados anteriores do projeto e não substituem este guia ou o README atual.
