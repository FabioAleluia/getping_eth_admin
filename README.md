# GetPing Admin - Sistema de Gestão de Usuários e Licenças

Sistema administrativo em **Python, Flask e SQLite** para gerenciar clientes, usuários e emitir/controlar licenças do **GetPing**.

---

## 🛠️ Tecnologias e Arquitetura

- **Backend**: Python 3.12, Flask, Werkzeug (hashing seguro scrypt)
- **Banco de Dados**: SQLite3 com WAL mode (`database/admin.db`)
- **Organização Modular**:
  - Blueprints em `routes/` (`auth.py`, `dashboard.py`, `clientes.py`, `licencas.py`, `api.py`)
  - CSS modular por página em `static/css/`
  - JavaScript modular por página em `static/js/`
  - Templates Jinja2 responsivos com Tailwind CSS e FontAwesome

---

## 🚀 Como Executar

1. **Ativar o ambiente virtual**:
   ```bash
   source venv/bin/activate
   ```

2. **Iniciar o servidor**:
   ```bash
   python app.py
   ```
   O painel estará acessível em `http://localhost:5001`.

3. **Credenciais Iniciais do Superadmin (Primeiro Acesso)**:
   - **Usuário**: `administrator`
   - **Senha**: `administrator`
   *(No primeiro login, o sistema exigirá obrigatoriamente a troca de senha para uma senha segura de 8 ou mais caracteres e contendo caracteres especiais).*

---

## 🔑 Endpoint da API para o GetPing

Para o sistema **GetPing** validar a licença:

- **Método**: `POST /api/v1/licenca/validar`
- **Exemplo de Payload JSON**:
  ```json
  {
    "chave_licenca": "GPING-XXXX-XXXX-XXXX-XXXX",
    "fingerprint": "UUID-DO-SERVIDOR-CLIENTE",
    "versao": "0.0.4"
  }
  ```
- **Exemplo de Resposta de Sucesso**:
  ```json
  {
    "valido": true,
    "chave_licenca": "GPING-XXXX-XXXX-XXXX-XXXX",
    "cliente": "Empresa XPTO",
    "tipo_plano": "Profissional",
    "limite_hosts": 50,
    "limite_agentes": 20,
    "expira_em": "2027-10-11 23:59:59",
    "dias_restantes": 365,
    "mensagem": "Licença ativa e autorizada."
  }
  ```
