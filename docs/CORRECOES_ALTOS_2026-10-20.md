# Correções dos achados altos — 20/10/2026

Referência: `ANALISE_2026-10-20.md`. O diagnóstico original permanece como histórico do estado antes desta alteração.

| Achado | Alteração | Situação |
|---|---|---|
| A1 — migração | Detecção comportamental da constraint em SQLite isolado; preservação de auth_version, índices/triggers explícitos e sequência; interrupção segura para colunas desconhecidas. | Código corrigido e regressões adicionadas. |
| A2 — bloqueio de login | Removido orçamento global por conta. Proteção precoce por IP mantida; orçamento por identificador/origem somente após CSRF e validação. | Código corrigido; ensaios com fontes distintas e credenciais corretas. |
| A3 — HTTP | Controle HTTPS configurável, origem canônica validada, HTTP da API rejeitado com 426, GET do painel redirecionado a origem fixa; exemplo Nginx atualizado. | Implementado e testado; certificado, domínio, proxy e ativação na máquina operacional ainda precisam ser configurados. |
| A4 — instalação | Autorização explícita de fingerprint por superadmin com senha atual/CSRF; licenças novas aguardam aprovação; transição individual das antigas; liberação não permite apropriação pelo próximo chamador. | Implementado; migração 002 e conferência de vínculos necessárias antes do uso. |

## Impactos

- Exige aplicar a migração 002 antes de iniciar a nova versão. Readiness também verifica a nova tabela/versão.
- Planos, limites, vencimentos, hashes e chaves não são alterados pela migração.
- Cookies já revogados não são revalidados ao atualizar variantes do schema; schemas equivalentes que já permitem assistente não são reconstruídos só por diferença de aspas.
- Licenças novas precisam da autorização do superadmin nos detalhes. Gestores podem continuar emitindo, mas a aprovação da instalação cabe ao superadmin.
- Licenças antigas não autorizadas mantêm compatibilidade até transição individual. Ativar o modo obrigatório global sem preparar os vínculos bloqueará essas instalações.
- Ao autorizar uma licença, ela exige o fingerprint confirmado mesmo com modo global em compatibilidade. Trocar o fingerprint autorizado faz o anterior deixar de funcionar. Liberar vínculo deixa a licença aguardando nova autorização, em vez de permitir que qualquer chamador a ocupe.
- O fingerprint observado pela API é informação histórica, não autorização. Mesmo um fingerprint autorizado pode ser copiado: autenticação criptográfica por instalação não foi implementada neste servidor isoladamente.
- HTTPS obrigatório está desativado por padrão durante a transição para preservar o teste de rede. A proteção só estará efetiva após configurar certificado/proxy/URL no ambiente. Não foi instalado certificado nem alterada configuração de sistema.
- Não há novo bloqueio global por conta, mas as cotas por IP continuam. Ataques distribuídos devem ser tratados também no proxy e por camadas adicionais de autenticação.

## Implantação

Siga o roteiro no README: pare o serviço para atualização, preserve código/configuração anteriores, faça backup consistente, ensaie em cópia, aplique init-db, confira dados e readiness e então reinicie. Não gere outra SECRET_KEY ao atualizar. O banco operacional não foi alterado durante o desenvolvimento.

A pergunta sobre domínio/IP e certificado foi enviada para concluir a configuração HTTPS específica do ambiente. Não foi escolhido endereço fictício para ativar essa proteção em produção.

## Validação

- **102 testes passaram**, incluindo preservação de cookie revogado em schema com aspas diferentes, reconstrução legada com auth_version/índice/trigger/sequence, tráfego dirigido de múltiplas origens e login legítimo, autorização de instalação, liberação segura e bloqueio HTTP.
- Testados fluxo de emissão/autorização/validação e rejeição de outra instalação; emissão nova não autoriza automaticamente a primeira máquina.
- Verificados HTTPS com proxy explicitamente confiável e rejeição de X-Forwarded-Proto não confiável.
- Ruff lint e formatação passaram; `git diff --check` sem problemas.
- Wheel construído e instalado em diretório temporário; script de verificação confirmou templates, CSS, JavaScript, schema, migrações, CLI e API da distribuição instalada.
- Banco operacional e serviços da máquina não foram alterados. A ativação HTTPS real continua pendente dos dados do ambiente solicitados.
