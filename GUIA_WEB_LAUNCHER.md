# Guia de Publicação do Web Launcher (1 Linha no PowerShell)

Este guia ensina como hospedar gratuitamente o **Utilitário SDSuper** na nuvem para que qualquer técnico consiga abrir o sistema em qualquer servidor de cliente apenas rodando **1 linha no PowerShell**, sem necessidade de instalação, pendrive ou configuração de portas.

---

## ⚡ Como funciona o comando no cliente

Quando você acessar o servidor do cliente (via AnyDesk, TeamViewer ou console local):
1. Abra o **PowerShell** (como Administrador ou usuário comum).
2. Cole o comando:
   ```powershell
   irm https://is.gd/sdsuper | iex
   ```
3. O script baixa automaticamente a versão mais recente em segundo plano, sobe o servidor local e abre o navegador em `http://localhost:8089` com o novo visual **Stitch Dark Mode**.

---

## 🚀 Passo a Passo para Hospedar Gratuitamente (5 Minutos)

### Passo 1: Criar um Repositório no GitHub (100% Grátis)
1. Acesse [github.com/new](https://github.com/new) e crie um repositório (público), por exemplo: `sdsuper-util`.
2. Faça o upload dos arquivos:
   - `start.ps1`
   - `Utilitario_SDSuper.exe` (ou publique no GitHub Releases).

### Passo 2: Criar uma "Release" no GitHub (Recomendado para arquivos .exe)
O GitHub Releases permite downloads diretos de altíssima velocidade via CDN da Microsoft:
1. No seu repositório no GitHub, clique em **Releases** > **Draft a new release**.
2. Defina uma tag (ex: `v4.2.0`).
3. Arraste e solte o arquivo `Utilitario_SDSuper.exe`.
4. Clique em **Publish release**.
5. Copie o link direto de download do `.exe` (ex: `https://github.com/SEU_USUARIO/sdsuper-util/releases/download/v4.2.0/Utilitario_SDSuper.exe`).

### Passo 3: Atualizar o link no `start.ps1`
Abra o arquivo [`start.ps1`](file:///c:/Users/backu/OneDrive/Utilidades%20-%20PDV,%20SUPER/Utilitario-Permissoes-Filial/start.ps1) e coloque o link do download na variável `$downloadUrl`:
```powershell
$downloadUrl = "https://github.com/SEU_USUARIO/sdsuper-util/releases/download/v4.2.0/Utilitario_SDSuper.exe"
```

### Passo 4: Obter o Link Raw do `start.ps1`
1. No GitHub, abra o arquivo `start.ps1` e clique no botão **Raw**.
2. Copie a URL (ex: `https://raw.githubusercontent.com/SEU_USUARIO/sdsuper-util/main/start.ps1`).

### Passo 5: Encurtar o Link para Facilitar a Digitação
Para não precisar digitar um link longo no AnyDesk do cliente:
1. Acesse [is.gd](https://is.gd) (ou [tinyurl.com](https://tinyurl.com)).
2. Cole o link Raw do passo anterior.
3. Escolha um nome personalizado, por exemplo: `sdsuper` ou `sdutil`.
4. Seu comando final ficará pronto:
   ```powershell
   irm https://is.gd/sdsuper | iex
   ```

---

## 🔒 Segurança & Privacidade
- O utilitário continua executando o back-end localmente no servidor do cliente, garantindo que o banco de dados Firebird e os dados fiscais da loja nunca sejam expostos para a internet pública.
- O bloqueio mestre do técnico por senha (`97557090`) permanece ativo para impedir acessos não autorizados.
