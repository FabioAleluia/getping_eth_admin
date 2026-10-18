# Análise técnica do GetPing Admin

Data: 17/10/2026. Escopo: fontes Python, schema local, templates, JavaScript, CSS, dependências, documentação, arquivos versionados e testes.

O projeto apresenta **2 achados críticos, 7 altos e 8 médios**. As condições de exploração estão descritas abaixo: uma configuração insegura no código não comprova que o servidor publicado usa essa configuração.

O sistema tem uma base simples e organizada, mas precisa corrigir autenticação, autorização e isolamento dos testes antes de uma exposição em produção. O mecanismo de licenciamento aceita reutilização da chave entre máquinas; o impacto depende da política comercial pretendida.

## Método e limites

- Leitura dos módulos e dos arquivos de interface, incluindo `database/schema.sql`, que existe localmente, mas não está versionado.
- Execução dos **25 testes existentes: todos passaram**, em cópia temporária dos fontes, com `DB_PATH` redirecionado antes de importar a aplicação. Foi usado o schema local original.
- Verificações adicionais com o test client do Flask e dados artificiais em SQLite temporário.
- Nenhuma alteração nos fontes de funcionamento ou nos dados do banco original. Apenas este relatório foi adicionado ao projeto.
- Não houve teste contra servidor remoto, teste de carga, análise de infraestrutura, histórico completo do Git ou auditoria do cliente GetPing. Não se pode concluir como o cliente aplica os limites, verifica o servidor ou se comporta offline.
- Não foi feita varredura de CVEs. Dependências sem versões fixas são um problema de reprodutibilidade, não prova de vulnerabilidade conhecida.

Critério: crítico permite comprometimento administrativo amplo; alto afeta materialmente segurança, disponibilidade ou dados; médio exige condições adicionais ou prejudica robustez, rastreabilidade e operação. A classificação é qualitativa, sem pontuação CVSS.

## Achados críticos

### C1 — Chave secreta padrão permite falsificar sessão administrativa

**Evidência:** `config.py:7`; uso de `session['user_id']` em `routes/auth.py:14` e `routes/auth.py:23`.

Sem `SECRET_KEY` no ambiente, todas as instalações usam um segredo conhecido no código. Quem conhece esse segredo pode assinar um cookie com o identificador de um usuário administrativo existente. A aplicação aceita a assinatura e carrega o usuário indicado, sem exigir login. Um token CSRF também pode ser incluído na sessão falsificada; a proteção CSRF não resolve esse comprometimento.

**Verificação:** cookie assinado externamente com o segredo padrão e ID de superadmin obteve HTTP 200 em `/usuarios/`, sem login. Cenário confirmado no ambiente temporário com configuração padrão.

**Correção:** exigir segredo aleatório fornecido por configuração segura e falhar na inicialização se ele estiver ausente ou for o padrão. Se o segredo padrão foi usado em produção, substituí-lo e invalidar as sessões antigas. Não manter o segredo comprometido como chave alternativa de validação.

### C2 — Gestor pode promover a si próprio ou um assistente a superadmin

**Evidência:** `routes/usuarios.py:120`, `routes/usuarios.py:128`, `routes/usuarios.py:160` e `routes/usuarios.py:169`.

A edição verifica o papel atual do usuário alvo, mas não verifica se o papel solicitado é permitido ao operador. O gestor pode editar a própria conta e enviar `papel=superadmin`; também pode promover um assistente. Limitar as opções do formulário não restringe uma requisição construída diretamente. O CHECK do banco permite `superadmin`, portanto não impede a elevação.

**Verificação:** POST de um gestor à edição da própria conta retornou 302 e persistiu `papel=superadmin`. O novo privilégio é carregado na requisição seguinte.

**Correção:** validar no servidor os papéis de origem e destino e a relação entre operador e alvo. Gestor deve poder administrar apenas os campos e perfis autorizados; mudança do próprio papel deve ser negada. Centralizar a política e adicionar testes negativos para promoção própria e de terceiros.

## Achados altos

### A1 — Conta inicial com credenciais públicas

**Evidência:** `database/db.py:72` e `database/db.py:77`; credenciais documentadas no README.

Uma instalação nova cria o superadmin com usuário e senha conhecidos. A troca obrigatória não protege contra alguém que faça o primeiro login antes do administrador legítimo: essa pessoa pode definir a nova senha. A conta também é recriada com essas credenciais se estiver ausente na inicialização.

**Condição:** instalação acessível antes da configuração inicial ou recriação da conta. Não foi verificada a senha do banco original.

**Correção:** bootstrap explícito por comando administrativo, senha aleatória de uso inicial ou segredo fornecido pelo operador, sem credencial universal. Restringir o acesso até concluir o provisionamento.

### A2 — Servidor de desenvolvimento com debug na execução documentada

**Evidência:** `app.py:49`; README recomenda `python app.py`.

Essa execução ativa debug e escuta em todas as interfaces. Exceções podem expor detalhes internos pelo debugger, com risco adicional associado ao console interativo. A execução remota de código não foi demonstrada; depende de exposição e das proteções do debugger. Isso não significa que uma implantação via WSGI tenha debug automaticamente ativo.

**Correção:** separar desenvolvimento e produção, desativar debug e usar servidor WSGI de produção atrás de HTTPS. Documentar o comando de produção e a configuração de acesso.

### A3 — Sessão de usuário excluído mantém acesso e pode emitir licença

**Evidência:** `routes/auth.py:14`, `routes/auth.py:28`, `routes/auth.py:32`; `routes/licencas.py:47` e `routes/clientes.py:57`.

Quando o usuário não existe mais, `g.user` fica vazio, mas `user_id` permanece na sessão. `login_required` verifica apenas a existência desse identificador. Algumas rotas bloqueiam assistentes apenas quando `g.user` existe, permitindo que a sessão órfã prossiga. Outras rotas acessam `g.user` diretamente e podem falhar com erro 500. Usuários inativos existentes, por outro lado, têm a sessão limpa.

**Verificação:** após excluir do banco temporário um assistente com sessão válida, a mesma sessão conseguiu emitir uma licença; a quantidade de licenças aumentou de 1 para 2.

**Correção:** limpar a sessão quando o usuário não existir ou estiver inativo. `login_required` deve exigir usuário válido e ativo. Autorizações devem negar acesso por padrão.

### A4 — Fingerprint não é validado e não restringe o uso da licença

**Evidência:** `routes/api.py:99`.

A API grava o primeiro fingerprint recebido, mas não compara os seguintes com o valor armazenado. Também aceita validação sem fingerprint. Possuir a chave basta para obter autorização em máquinas diferentes.

**Verificação:** a mesma chave recebeu HTTP 200 e `valido=true` para máquina A, máquina B e fingerprint omitido.

**Impacto:** alto se a licença deve ser vinculada a uma instalação. Se o produto permite múltiplas instalações por chave, isso precisa ser explicitado e modelado; a ausência de comparação não é, isoladamente, violação dessa política.

**Correção:** definir se a unidade de licença é cliente, instalação ou conjunto de instalações. Para vínculo único, exigir identificação, comparar vínculo e realizar ativação atômica, com procedimento autorizado de transferência. Um fingerprint informado pelo cliente é copiável; avaliar credencial por instalação e prova de posse para uma vinculação mais forte.

### A5 — Testes podem apagar os dados reais e substituir senha administrativa

**Evidência:** `test_permissoes_assistente.py:7`, `test_permissoes_assistente.py:10` e `test_fluxo.py:6`; caminho fixo em `database/db.py:9`.

Os testes usam a mesma configuração de banco da aplicação. Há exclusão geral de logs, licenças, clientes e usuários diferentes de `administrator`, além da substituição da senha administrativa. `TESTING=True` não redireciona o banco. A importação de `app.py` já inicializa o banco antes de ajustes posteriores.

**Correção:** injetar caminho do banco na factory antes de qualquer inicialização, usar banco temporário por teste e impedir a execução destrutiva sobre banco de operação. Os testes desta análise foram executados com redirecionamento prévio e cópia temporária justamente para evitar esse efeito.

### A6 — Clone do repositório não contém o schema necessário para iniciar

**Evidência:** `.gitignore:15` ignora `*.sql`; `database/schema.sql` não consta em `git ls-files`; `database/db.py:36` exige esse arquivo em toda inicialização.

O arquivo existe nesta máquina, mas não acompanha um clone normal do estado versionado. Uma instalação ou recuperação baseada somente no Git falha com `FileNotFoundError`, inclusive se já houver banco, pois o schema é aberto incondicionalmente.

**Correção:** versionar o schema e as migrações, restringindo o ignore a dumps que realmente devam ser excluídos. Validar instalação em checkout limpo. O banco contém dados e deve continuar fora do Git.

### A7 — API pública produz escrita e crescimento de logs sem controle local

**Evidência:** `routes/api.py:37`, `routes/api.py:112`; `database/db.py:16`; ausência de limitação de requisições nas rotas e configuração.

Até chaves inexistentes geram INSERT. Validações bem-sucedidas também atualizam a licença e gravam log. Não há política de retenção, tamanho de campos JSON ou limitação de requisições na aplicação. Tráfego abusivo pode consumir armazenamento e disputar o escritor do SQLite, prejudicando painel e validação de licenças legítimas.

**Condição:** não foi inspecionado eventual controle no proxy. Saturação não foi provocada.

**Correção:** limitar frequência e payload, usar cotas por origem e por credencial, definir retenção e agregação/amostragem de falhas, monitorar disco e latência. Proteger também o login contra tentativas automatizadas e consumo excessivo de hashing.

## Achados médios

### M1 — Entradas inválidas provocam exceções ou persistem dados inadequados

**Evidência:** `routes/api.py:11`, `routes/api.py:80`, `routes/licencas.py:57`, `routes/licencas.py:109` e `routes/licencas.py:112`; constraints em `database/schema.sql`.

JSON precisa ser objeto, mas listas são aceitas até falhar em `.get()`. Campos numéricos ou nulos falham em `.strip()`. Conversões `int()` sem tratamento falham para texto ou vazio. A data de edição é concatenada sem parsing prévio: um valor inválido pode ser salvo e interromper as futuras validações dessa licença. Limites negativos não têm CHECK no schema, e os limites HTML são contornáveis. Plano/status inválidos podem acionar CHECK e virar 500 sem tratamento.

**Verificação:** lista JSON, chave numérica e chave nula produziram `AttributeError`; data inválida foi salva e causou `ValueError` na validação seguinte. Em execução normal, essas exceções se tornam respostas 500.

**Correção:** validar tipo, formato, tamanho, faixas, enums e relações antes de persistir. Retornar 400/422 com contrato JSON consistente na API; apresentar erro de campo no painel. Adicionar constraints de faixa como defesa complementar e tratar violações de integridade.

### M2 — Alteração ou reset de senha não revoga sessões já emitidas

**Evidência:** `routes/auth.py:135`, `routes/auth.py:172` e `routes/usuarios.py:157`; sessão contém apenas referência ao usuário, sem versão de autenticação.

Mudar o hash não invalida cookies existentes. Mesmo após redefinição da senha, uma sessão obtida anteriormente continua válida enquanto as demais condições permitirem. Exigir troca de senha não equivale a revogar sessões: uma sessão antiga pode acessar o fluxo de primeiro acesso.

**Correção:** armazenar versão de autenticação na conta e na sessão, incrementando-a em resets e eventos de segurança; alternativamente, usar sessões revogáveis no servidor. Testar com dois clientes independentes.

### M3 — Falta trilha de auditoria das ações administrativas

**Evidência:** mutações em `routes/usuarios.py`, `routes/clientes.py` e `routes/licencas.py`; `licenca_logs` registra principalmente consultas da API.

Mudanças de papel, senha, limites, validade, bloqueios e exclusões não registram operador, valores anteriores e posteriores ou justificativa. Isso limita investigação de fraude, erro operacional e incidentes. A exclusão de licença preserva logs existentes com `licenca_id=NULL` pelo schema local, mas a própria exclusão não ganha evento administrativo.

**Correção:** auditoria na mesma transação da mudança, com ator, alvo, momento, ação e diferenças relevantes. Restringir acesso, definir retenção e nunca registrar senhas, hashes ou tokens completos.

### M4 — Cookie sem Secure e ausência de proteções HTTP no projeto

**Evidência:** `config.py:8`; ausência de `SESSION_COOKIE_SECURE` e de configuração de cabeçalhos de proteção na aplicação. Templates carregam JavaScript externo.

O cookie não exige HTTPS por configuração local. Não há CSP ou proteção explícita contra enquadramento. O impacto efetivo depende de HTTPS e cabeçalhos eventualmente aplicados fora do projeto, que não foram inspecionados.

**Correção:** HTTPS obrigatório, cookie Secure em produção e cabeçalhos adequados, incluindo proteção contra framing. Construir CSP compatível com scripts e estilos atuais; aplicar HSTS após validar a operação por HTTPS. Manter HttpOnly e SameSite já existentes.

### M5 — IP de auditoria pode ser falsificado pelo cabeçalho recebido

**Evidência:** `routes/api.py:15`.

A API aceita diretamente `X-Forwarded-For`. Sem proxy que remova/reconstrua o cabeçalho, o cliente escolhe o valor gravado; mesmo com proxy, pode ser registrada uma lista em vez de um IP validado. Esse campo não é usado atualmente para autorização, mas perde confiabilidade para investigação.

**Correção:** confiar somente em proxies conhecidos, configurar a quantidade correta de saltos e obter o IP da requisição após o tratamento de proxy. Não basear controles de acesso no cabeçalho bruto.

### M6 — Status e indicadores de expiração usam critérios diferentes

**Evidência:** `routes/api.py:79`, `routes/dashboard.py:16`, `routes/dashboard.py:19`, `routes/clientes.py:22` e `routes/licencas.py:23`.

A API muda o status para expirada apenas quando consultada. Listagens filtram o status persistido; o painel cruza status com a data do dia, enquanto a API usa horário exato. Contagens de clientes tratam toda licença com status ativa como ativa, inclusive vencida. Clientes inativos também não são descontados do indicador de licenças ativas do dashboard. Uma licença pode aparecer ativa em uma tela e ser negada na API.

**Correção:** definir um estado efetivo comum que considere cliente, status e instante de expiração, reutilizando-o em consultas e relatórios. Definir explicitamente UTC e a apresentação em America/Sao_Paulo: hoje, 23:59:59 UTC corresponde a 20:59:59 em São Paulo. O retorno de data deve informar o fuso.

### M7 — Listagens sem paginação e consultas sem limites de busca

**Evidência:** `routes/clientes.py:12`, `routes/licencas.py:11` e `routes/usuarios.py:12`.

As listagens carregam todos os resultados com `fetchall()`. Busca com `%texto%` pode percorrer muitas linhas, e as contagens por cliente crescem com o volume. Isso aumenta tempo de resposta e uso de memória.

**Correção:** paginação com tamanho máximo, ordenação estável, limites de busca e avaliação dos planos de consulta com volume representativo. Medir antes de acrescentar índices: o schema já tem índices por chave, cliente, licença no log e data do log.

### M8 — Dependências e entrega não são reprodutíveis

**Evidência:** `requirements.txt:1`, `templates/base.html:8`, `templates/auth/login.html:7` e lista de arquivos do Git.

Dependências usam somente versão mínima, sem resolução fixa; uma instalação futura pode receber versões diferentes. Tailwind é executado por CDN em tempo de uso. Há bytecode `__pycache__` versionado. O README informa `database/admin.db`, mas o código usa `database/db_getping.db`, e não documenta instalação limpa e implantação de produção.

**Correção:** fixar versões resolvidas com processo de atualização e auditoria, compilar CSS e servir os artefatos, remover bytecode do versionamento e alinhar documentação. Configuração de segredos deve ter exemplo sem valores reais. A existência de `python-dotenv` nas dependências não implica que uma execução direta com `python app.py` carregue `.env`: o código não chama `load_dotenv()`.

## Permissões de assistente: decisão de negócio a revisar

`test_permissoes_assistente.py:202` exige explicitamente que assistente possa alterar plano, limites, status e validade. Portanto, esse acesso não foi contado como bypass da regra atual.

Ainda assim, o papel descrito na interface como consulta e suporte pode converter uma licença básica em Enterprise ou ampliar validade. Isso tem impacto financeiro e deve ser uma autorização consciente. Definir matriz por ação e por campo; se suporte não deve alterar condições comerciais, restringir backend e atualizar o teste correspondente.

O endpoint devolve limites de hosts/agentes, mas este repositório não contém a aplicação cliente. Não há evidência suficiente para afirmar que esses limites são efetivamente aplicados ou que podem ser burlados no GetPing.

## Qualidade dos testes e verificações realizadas

Os testes existentes cobrem login, troca obrigatória de senha, criação de clientes/licenças, bloqueios de exclusão, algumas permissões, CSRF e licença suspensa/expirada. Passaram **25/25** na execução isolada, em aproximadamente 7 segundos.

O teste de interface do assistente consulta `/dashboard/` em `test_permissoes_assistente.py:166`, mas a rota real é `/`. Como verifica apenas ausência de botão e não exige HTTP 200, uma página 404 pode satisfazer a asserção. Corrigir a URL e verificar status e conteúdo positivo.

Verificações adicionais confirmaram:

| Cenário | Resultado observado |
|---|---|
| Gestor envia papel superadmin na própria edição | Papel persistido como superadmin |
| Cookie assinado com segredo padrão, sem login | `/usuarios/` respondeu 200 |
| Licença em fingerprints A, B e omitido | Três autorizações válidas |
| Sessão de assistente depois da exclusão da conta | Nova licença criada |
| Lista JSON / chave numérica / chave nula | AttributeError |
| Salvar data inválida e validar a licença | Persistência aceita; ValueError na API |

Adicionar testes de regressão para esses cenários; acrescentar revogação após reset de senha, limites negativos, cliente inexistente/inativo na emissão, contrato JSON de erros, expiração no instante limite e concorrência na ativação. Incluir teste de instalação em clone limpo e impedir qualquer teste de apontar para banco operacional.

## Melhorias e ordem de execução

1. **Contenção imediata:** exigir segredo seguro, corrigir promoção de papéis e sessões órfãs, eliminar credencial inicial universal e retirar debug da execução de produção.
2. **Entrega segura:** versionar schema/migrações e isolar banco de teste antes da importação. Fazer backup consistente e ensaiar restauração; por usar WAL, não depender de copiar apenas o `.db` enquanto há atividade.
3. **Licenciamento:** estabelecer política por instalação, implementar ativação/transferência atômica e definir explicitamente como o cliente opera sem conectividade. Avaliar autorização assinada e curta com validade e vínculo se houver cache offline, após revisar o cliente.
4. **Robustez:** validação central de entradas, respostas JSON de erro, limites de requisição/payload, retenção de logs, revogação de sessões e auditoria administrativa.
5. **Operação:** implantação WSGI/HTTPS, configuração por ambiente, health/readiness sem revelar segredos, monitoramento de falhas de licença, latência, disco e erros de banco, e documentação de recuperação.
6. **Manutenção:** separar validação/regra de negócio dos handlers, centralizar permissões e estado efetivo da licença, paginar consultas e manter dependências reproduzíveis. SQLite pode continuar adequado para carga pequena; migrar para outro banco deve decorrer de métricas de concorrência e disponibilidade.

A migração embutida em `init_db()` também merece substituição por migrações versionadas: ela recria a tabela de usuários durante a inicialização, depende do texto do CHECK e alterna `PRAGMA foreign_keys` junto a operações transacionais. A mudança desse PRAGMA não tem efeito dentro de uma transação ativa, conforme documentação SQLite. Não foi demonstrada perda de dados no schema atual, que já contém assistente; testar o caminho legado com suas referências antes de utilizá-lo em produção.

## Pontos positivos

- Blueprints e separação de templates, CSS e JavaScript tornam o projeto fácil de navegar.
- Consultas analisadas usam parâmetros para valores; não foi encontrada injeção SQL direta nesses caminhos.
- Senhas usam as funções de hash do Werkzeug; não são persistidas em texto claro.
- Há CSRF nas mutações do painel, limpeza de sessão no login, HttpOnly e SameSite.
- Banco usa foreign keys, transações com rollback e WAL; o schema local preserva logs ao excluir licença com ON DELETE SET NULL.
- API verifica cliente ativo, status e expiração antes de autorizar. A isenção de CSRF da API não é, por si só, uma falha: o endpoint usa a chave de licença, não a sessão administrativa como autorização.

## Referências técnicas

- [Configuração do Flask: segredo, cookies e limites](https://flask.palletsprojects.com/en/stable/config/).
- [Implantação de produção do Flask](https://flask.palletsprojects.com/en/stable/deploying/).
- [SQLite: PRAGMA foreign_keys](https://www.sqlite.org/pragma.html#pragma_foreign_keys).

As referências explicam os mecanismos e recomendações; os achados específicos foram obtidos no código local e nas verificações isoladas descritas neste relatório.
