# Utilitário SDSuper - Assistente de Permissões e Virada de Filial / CNPJ

Utilitário profissional desenvolvido para facilitar e automatizar tanto a **preparação prévia de permissões** quanto a **virada oficial de filial e migração de CNPJ** diretamente no banco de dados Firebird 3.0 do sistema **SDSuper**, com validação em tempo real e proteção contra alterações prematuras.

---

### Arquitetura em Duas Etapas

Para garantir total segurança e continuidade operacional do cliente, as ações do utilitário foram divididas em duas etapas claras:

#### 🛡️ Etapa 1: Permissões e PDVs (Seguro executar com antecedência)
Pode ser executada dias ou semanas antes da virada sem qualquer impacto no funcionamento atual da loja:
- **Replicar Permissões SDSuper**: Clona em massa as permissões da Filial de Origem para a Filial de Destino na tabela `PERMISSOES` usando a fórmula oficial do gerador (`GEN_ID(GENIDPERMISSAO, 1) * 10 + 1`).
- **Adicionar Filial nos PDVs (Apenas Operadores de Caixa)**: Acrescenta a nova filial (ex: `'02'`) em `WFILIAISPDVS` **exclusivamente** para quem já possui permissões ativas de PDV (`WPERMISSOESPDVS`). Usuários administrativos permanecem protegidos para não aparecerem nos caixas.

#### ⚠️ Etapa 2: Virada Oficial de Filial / Migração de CNPJ (MOMENTO DA VIRADA)
> **Ponto de Atenção do Técnico:** Estas opções alteram a estrutura do banco e redirecionam o acesso dos operadores. **Execute somente na data e hora oficial da migração de filial/CNPJ.** Se executado antes, os operadores podem perder o acesso à filial antiga antes da hora!

1. **Alterar ID Padrão do Sistema (`GENIDFILIALPADRAO`)**:
   - Altera o generator `GENIDFILIALPADRAO` para o ID da nova filial (ex: Filial 2).
   - O SDSuper lê este sequencial ao iniciar para carregar a filial ativa padrão da estação.
   - Exibe badge em tempo real com o valor atual registrado no banco.
2. **Alterar "Filial Acesso / Trabalho" dos Usuários (`WIDFILIALTRABALHO`)**:
   - Altera a filial de trabalho de todos os usuários selecionados.
   - **Deve ser executado em conjunto com a troca de ID padrão da filial acima** para que todos consigam se conectar normalmente ao novo CNPJ.
3. **Alterar Filial Cadastro de Produtos (`CONTROLE.WIDFILIALPRODUTOS`)**:
   - Altera a filial responsável pelo cadastro de produtos na tabela `CONTROLE`.
   - Garante que novos produtos e espelhos cadastrados sejam vinculados diretamente ao novo CNPJ.
   - Exibe badge em tempo real com o status atual do banco.
4. **Sincronizar Versão do Banco (`FILIAISCONTROLE.WVERSAOBANCO`)**:
   - Copia a versão mais atualizada registrada no banco (ex: `11740`) para a nova filial na tabela `FILIAISCONTROLE`.
   - Evita o erro clássico de *"Versão incompatível do banco de dados"* ao tentar efetuar login na nova filial.
   - Detecta automaticamente se a versão está pendente ou já sincronizada.
5. **Alterar "Filial Cadastro" Base (`WIDFILIAL`)**:
   - Opcional, para migrar também o cadastro base dos usuários selecionados.

---

### 🏢 Aba 2: Cadastro & Dados da Filial / CNPJ (Tabela `FILIAIS`)

Permite configurar ou cadastrar qualquer filial diretamente pelo utilitário, eliminando a necessidade de navegar por mais de 5 telas diferentes no SDSuper:

- **Consulta Automática de CNPJ**: Integração em tempo real com APIs da Receita Federal (BrasilAPI e ReceitaWS) preenchendo automaticamente Razão Social, Fantasia, CEP, Logradouro, Número, Complemento, Bairro, Cidade, UF, E-mail e Telefone.
- **Auto-Resolução de Cidades e Bairros**: Vincula as chaves estrangeiras `WIDCIDADE` (base oficial de 5.594 municípios) e `WIDBAIRRO` (com auto-inclusão via gerador `GENIDBAIRRO` caso o bairro ainda não exista).
- **Clonagem do Contador em 1 Clique**: Botão para copiar instantaneamente os 12 campos de assessoria contábil (nome, CNPJ, CPF, CRC, endereço, telefone, e-mail) a partir da Filial 1.
- **Vínculos Operacionais Pré-Configurados**: Presets para filial 100% independente ou filial compartilhando preços/estoque/comandas com a matriz.
- **Rede e Terminal (Servidor Windows - Passo 5)**: Detecta automaticamente o IP local do servidor Windows onde o utilitário está sendo executado e formata o caminho de rede compartilhado `\\{IP_LOCAL}\SDPROGS$\SDTERMINAL\` e o IP do concentrador PDV (`WIPPDV`).

---

### Recursos Adicionais

- **Detecção Automática do Registro do Windows**: Identifica se a máquina possui o SDSuper instalado e detecta o IP do servidor Linux ou `LOCALHOST` a partir de `HKLM\SOFTWARE\WOW6432Node\SDInformatica\SDSuper`.
- **Filtro Automático de Usuários de Sistema**: Oculta automaticamente contas internas e de integração (`ADMINISTRADOR`, `ACS AUTOMACAO`, `ETIQUETA`, `NORTH SISTEMAS`, `SD `, etc.).
- **Transação Atômica**: Todas as operações (permissões, usuários e tabelas estruturais de sistema) são gravadas com commit atômico e rollback automático em caso de falha.
- **Executável Portátil Standalone**: Executável único (`Utilitario_SDSuper.exe`), sem necessidade de Python ou dependências instaladas no servidor.

---

### Como Iniciar

1. Basta executar o arquivo:
   [`INICIAR_UTILITARIO.bat`](file:///c:/Users/backu/OneDrive/Utilidades%20-%20PDV,%20SUPER/Utilitario-Permissoes-Filial/INICIAR_UTILITARIO.bat) ou [`Utilitario_SDSuper.exe`](file:///c:/Users/backu/OneDrive/Utilidades%20-%20PDV,%20SUPER/Utilitario-Permissoes-Filial/Utilitario_SDSuper.exe)
2. Acesse no navegador: [http://localhost:8089](http://localhost:8089)
