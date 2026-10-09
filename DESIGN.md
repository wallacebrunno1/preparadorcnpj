# Design System: SDSuper Stitch Dark UI

Inspirado na linguagem visual do **Google Stitch AI UI Design** (Deep Obsidian, Bento Grid & Aurora Glow).

## 1. Identidade & Filosofia Visual
- **Tema**: Dark Mode de alta fidelidade com paleta base obsidiana cósmica (`#07090E`).
- **Composição**: Layout estilo Bento Grid com cantos arredondados generosos (`16px` a `20px`), superfícies em vidro translúcido (`backdrop-filter: blur(20px)`), bordas ultrafinas de 1px (`rgba(255, 255, 255, 0.08)`) e iluminação suave via gradientes radiais.
- **Micro-interações**: Transições aceleradas por GPU (`opacity` e `transform`), garantindo sensação de fluidez e elegância sem sobrecarregar a renderização (Zero layout thrashing).

---

## 2. Paleta de Cores e Tokens

### Superfícies (Canvas & Bento Cards)
- `--bg-body`: `#07090E` (Obsidiana Profunda)
- `--bg-card`: `rgba(14, 20, 36, 0.75)` (Glass Card)
- `--bg-card-hover`: `rgba(22, 31, 54, 0.90)`
- `--bg-input`: `rgba(9, 13, 24, 0.75)`
- `--border-color`: `rgba(255, 255, 255, 0.08)`
- `--border-color-hover`: `rgba(255, 255, 255, 0.16)`
- `--border-focus`: `#6366F1` (Índigo Stitch)

### Acentos & Cores de Estado
- **Stitch Primary (Índigo/Azul)**: `#6366F1` / `#3B82F6` / `#2563EB`
- **Cyan Elétrico**: `#38BDF8` (Destaques e Ícones)
- **Violeta / Púrpura**: `#8B5CF6` / `#A855F7`
- **Esmeralda (Sucesso & Operação Online)**: `#10B981` / `#34D399`
- **Âmbar (Atenção & Standby)**: `#F59E0B` / `#FBBF24`
- **Rose (Erro & Remoção)**: `#F43F5E` / `#FB7185`

### Gradientes de Destaque
- **Stitch Brand**: `linear-gradient(135deg, #38BDF8 0%, #6366F1 50%, #A855F7 100%)`
- **Botão Primário**: `linear-gradient(135deg, #2563EB 0%, #4F46E5 50%, #7C3AED 100%)`
- **Botão Sucesso**: `linear-gradient(135deg, #059669 0%, #10B981 100%)`

---

## 3. Tipografia
- **Títulos & Display**: `Plus Jakarta Sans` (pesos 600, 700, 800), tracking `-0.02em`.
- **Corpo & Interface**: `Inter` / `Plus Jakarta Sans` (pesos 400, 500, 600).
- **Código, IDs & Números**: `JetBrains Mono` (pesos 500, 600).

---

## 4. Componentes Principais

### Navegação (Floating Pill Toolbar)
- Trilho flutuante pill com cantos `9999px`.
- Botões de aba pill com micro-elevação ao passar o mouse e gradiente acetinado quando ativos.

### Botões e Controles de Ação
- **Botão Primário**: Gradiente Stitch com destaque interno (`inset 0 1px 0 rgba(255,255,255,0.25)`), elevação suave no hover e recuo elástico no clique (`:active { transform: scale(0.97); }`).
- **Botão Secundário**: Vidro escuro translúcido com borda suave, ganhando brilho no hover.
- **Chips / Presets**: Formato pílula (`border-radius: 9999px`) para seleção rápida de ambiente (VM Linux, Windows Local, DDNS, etc.).

### Floating Action Bar (Barra de Execução)
- Dock flutuante na parte inferior da tela, arredondado `9999px`, com backdrop blur de 24px, borda brilhante e contador em tempo real de operadores selecionados.

---

## 5. Diretrizes de Animação
- **Fade In de Telas & Abas**: `@keyframes stitchFadeIn` (0.28s, translateY de 10px para 0, opacidade de 0 para 1).
- **Modais**: Entrada suave combinando fade no backdrop com leve escala (`0.96` para `1.0`) na caixa de diálogo.
- Todas as animações utilizam exclusivamente propriedades de composição (`opacity` e `transform`), mantendo 60/120fps sem engasgos ou consumo desnecessário de CPU.
