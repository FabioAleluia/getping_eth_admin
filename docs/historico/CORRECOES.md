# Correções implementadas

Este documento acompanha a análise original em `ANALISE_TECNICA.md`, que permanece como registro do diagnóstico anterior às alterações.

## Cobertura dos achados

| Achado | Implementação |
|---|---|
| C1: segredo conhecido | Configuração obrigatória, rejeição do segredo antigo, ausência de fallback e regressão de cookie forjado. |
| C2: promoção de gestor | Validação de papel destino no servidor; bloqueio de alteração do próprio papel e promoção por gestor. |
| A1: credencial inicial universal | Provisionamento explícito, sem criação automática; login com senha antiga proibido; comando local de recuperação. |
| A2: debug e servidor de desenvolvimento | Debug removido, dependências e exemplos para WSGI/HTTPS. Execução direta mantém bind 0.0.0.0 para o teste entre máquinas solicitado. Publicação depende de configurar o ambiente. |
| A3: sessões órfãs | Usuário precisa existir, estar ativo e apresentar versão de autenticação válida. |
| A4: fingerprint | Modo obrigatório implementado e testado, ativação atômica e liberação por superadmin. Permanece desligado por compatibilidade até validação do cliente. |
| A5: testes destrutivos | Banco temporário por teste; nenhuma inicialização na importação; proteção de configuração TESTING. |
| A6: schema ausente no clone | Schema e migrações retirados da regra de exclusão do Git; inicialização explícita. Arquivos devem acompanhar o próximo commit. |
| A7: abuso da API | Cotas persistidas compartilhadas, limite de payload, supressão de logs de chave desconhecida, agregação de check-ins e comando de retenção. Agendamento depende da operação. |
| M1: entradas inválidas | Validação de tipos, tamanhos, enums, números, datas e cliente ativo; triggers de faixa/data; erros HTTP e JSON controlados. |
| M2: revogação | Versão da autenticação incrementada em troca/reset e edição administrativa; revogação testada com clientes independentes. |
| M3: auditoria | Eventos na transação de mutações administrativas; sem hashes/senhas ou chaves de licença completas. |
| M4: cabeçalhos/cookies | Cookie Secure em produção, CSP, proteção contra framing, nosniff, HSTS em HTTPS e exemplos de proxy. TLS precisa ser implantado. |
| M5: IP falsificado | Cabeçalhos encaminhados ignorados por padrão, ProxyFix explícito para topologia confiável. |
| M6: estado divergente | Estado efetivo comum no painel, contagens, detalhes e API; formato ISO com fuso adicionado sem quebrar campo antigo. |
| M7: listagens | Paginação de 50 registros, limite de busca e navegação que preserva filtros. |
| M8: entrega | Dependências fixadas, CSS compilado local, bytecode retirado da árvore versionada e documentação de instalação/recuperação. |

## Alterações de comportamento

- Todas as sessões anteriores à atualização serão encerradas. É necessário configurar e preservar uma nova chave secreta segura.
- A senha inicial antiga não permite mais login. Use `reset-password` localmente para recuperar contas legadas que ainda a utilizam.
- Assistentes não alteram condições comerciais por padrão; permissão antiga existe como opção explícita de configuração.
- Logout usa POST com CSRF. Links antigos para GET `/logout` recebem 405.
- O formato de chave antigo é preservado por padrão. Chaves de 128 bits estão disponíveis com `GETPING_EXTENDED_KEYS=1`, após verificar se o cliente aceita o formato maior.
- Datas continuam em UTC. O campo anterior da API foi preservado e um campo ISO explícito foi adicionado.
- Logs de validação são agregados e não contêm mais a chave completa em novos eventos. Eventos antigos não foram modificados automaticamente.
- O banco não é migrado automaticamente ao importar o módulo ou iniciar workers. Atualização exige `init-db` antes de iniciar o serviço.

## Implantação

O banco operacional não foi alterado durante o desenvolvimento. Backup, migração, configuração de segredos, HTTPS, serviço, monitor externo e agendamento de retenção devem seguir o roteiro do README no ambiente de implantação. Os exemplos de domínio, usuário e caminhos não são configurações instaladas.

O cliente GetPing não está neste repositório. Vínculo obrigatório deve ser ativado somente após validar os fingerprints existentes e o cliente. Autorização offline assinada e comprovação criptográfica por instalação exigem trabalho também nesse cliente; o servidor atual não deve ser apresentado como proteção contra clonagem do próprio fingerprint.

## Validação realizada

- **62 testes passaram**: 25 testes de fluxo ajustados para isolamento e 37 regressões adicionais.
- Suíte executada também com dependências instaladas em diretório temporário independente, sem usar os pacotes do ambiente virtual original; execução final com ResourceWarning tratado como erro.
- Testadas migração legada, preservação de referências, rollback em erro, idempotência, backup e leitura/restauração do backup em SQLite separado.
- Instalação nova validada com `init-db`, provisionamento interativo, `check-data`, health check e `gunicorn --check-config`.
- CSS compilado com Tailwind 3.4.17 e páginas principais renderizadas pelo test client.
- `git diff --check` sem problemas. Banco original permaneceu com a data de modificação anterior ao trabalho.
- Não houve publicação, alteração do banco operacional, inspeção visual em navegador real ou teste do cliente GetPing; HTTPS e monitoramento externos dependem da implantação.


## Continuidade — segunda etapa

- Sessões do painel têm limite de 30 minutos de inatividade e 24 horas de duração total. Chamadas da API não renovam o painel; sessões antigas exigem login novamente.
- A própria conta é editada pelo perfil, com exigência da senha atual para troca; o cadastro administrativo não permite contornar essa confirmação.
- O perfil permite revogar todas as sessões, incluindo cookies copiados; a revogação é auditada.
- Consulta de auditoria no painel exclusiva a superadmin, com filtros, paginação e escape dos valores exibidos. Login/logout passam a registrar operador, sem senha ou hash.
- Health check também verifica as estruturas de segurança e o registro da migração esperada.
- `security-check` verifica integridade, estrutura, recomendações de configuração, senha legada e quantidade de licenças ativas sem vínculo, sem modificar registros ou revelar credenciais. O modo `--strict` retorna erro nas recomendações pendentes.
- Exemplos de serviço/timer de retenção diária preparados, sem instalação no sistema.
- A comunicação validada entre máquinas foi preservada: execução direta em 0.0.0.0, sem ativar fingerprint obrigatório ou mudar o contrato da API.

Não há nova migração nesta etapa. A estrutura da primeira etapa precisa estar aplicada. HTTPS, firewall, instalação do serviço/timer e validação do cliente antes de exigir fingerprint continuam dependentes do ambiente de implantação. Nenhum deles foi apresentado como já implantado.

Validação desta etapa: **77 testes passaram**, sendo os 62 anteriores e 15 novos testes de sessão, revogação, confirmação de senha, auditoria, diagnóstico e health check. Execução com bancos temporários e ResourceWarning tratado como erro. CSS recompilado e `git diff --check` sem problemas. Não foi aplicado ajuste no banco operacional nem instalada configuração de sistema nesta etapa.

## Reorganização estrutural — 17/10/2026

- Aplicação transferida para o pacote regular `getping_admin`, com templates, static e SQL incluídos na distribuição instalável.
- Testes centralizados em `tests/`; sessão/autenticação, auditoria, migrações e geração de chaves separadas das views e da conexão SQLite.
- Configuração lida a cada factory, com precedência dos overrides, cookie Secure derivado do ambiente final e rejeição de configuração inválida de proxy.
- Validação de formulários declarada nas views por decorador; preservados CSRF, limites de payload e regras específicas das operações.
- Removidos dez arquivos de bytecode versionados, três JavaScripts de console e três folhas CSS sem seletores usados. Includes ajustados e CSS Tailwind recompilado.
- Novas instalações usam o diretório de instância; banco legado existente continua selecionado e `GETPING_DATABASE` mantém precedência. Nenhum banco operacional foi movido ou migrado.
- `app.py` preservado como entrada de compatibilidade; documentação, build e exemplos de serviços atualizados para o pacote.
- Adicionados `pyproject.toml`, configuração Ruff, workflow de CI e verificação de recursos do wheel instalado.

Validação local: **86 testes passaram**, incluindo os 77 anteriores e nove regressões de configuração/formulários; Ruff e formatação sem pendências; wheel construído e instalado fora do checkout com dependências de execução já disponíveis, seguido de verificação de templates, assets, schema, migração, CLI, API e configuração Gunicorn. A CI foi preparada, mas não executada no GitHub nesta etapa. Não houve publicação ou inspeção visual em navegador.

A estrutura e os comandos atuais estão em [desenvolvimento](../desenvolvimento.md) e no [README](../../README.md).
