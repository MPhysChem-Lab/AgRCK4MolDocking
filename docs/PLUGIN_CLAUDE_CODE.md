# Instalar como plugin no Claude Code

O repositório é ao mesmo tempo **plugin** (`.claude-plugin/plugin.json`) e **marketplace**
(`.claude-plugin/marketplace.json`, marketplace `agrck`, plugin `agrck4moldocking`).

## 1. Pré-requisito: acesso ao repositório privado
O Claude Code não pede senha. O clone precisa funcionar sem interação:
```bash
gh auth login            # HTTPS com credential helper do gh
# ou chave SSH sem senha cadastrada no GitHub
export CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1   # opcional: força HTTPS
```

## 2. Adicionar o marketplace e instalar
Dentro do Claude Code:
```text
/plugin marketplace add fatioleg/AgRCK4MolDocking
/plugin install agrck4moldocking@agrck
```
Ou pelo terminal:
```bash
claude plugin marketplace add fatioleg/AgRCK4MolDocking
claude plugin install agrck4moldocking@agrck --scope user
```
Reinicie a sessão. Verifique com `/plugin`: em *Installed*, devem aparecer 6 skills, 4 agents, hooks e o MCP
`pymol`.

## 3. O que o plugin traz
| Componente | Itens |
|---|---|
| Skills | `agrck-iniciar`, `agrck-estruturas`, `agrck-docking`, `agrck-figuras`, `agrck-interacoes`, `agrck-relatorio` |
| Subagentes | `agrck-executor` (haiku/low), `agrck-analista` (sonnet/medium), `agrck-redator` (sonnet/medium), `agrck-revisor` (opus/high) |
| Hooks | `PreToolUse` → `hooks/guard.py`; `PostToolUse` → `hooks/lint_report.py` |
| CLI | `bin/agrck` entra no PATH enquanto o plugin está ativo |
| MCP | `pymol` → comando `${AGRCK_PYMOL_MCP:-agentic-pymol}` |

## 4. Configuração do ambiente científico
O plugin traz o agente. As ferramentas científicas ficam num Python seu (veja [INSTALACAO.md](INSTALACAO.md)).
Aponte para elas:
```bash
export AGRCK_PYTHON=/caminho/.venv/bin/python          # Python com rdkit, prolif, posebusters...
export AGRCK_PYMOL_PYTHON=/caminho/pymol_os/bin/python  # PyMOL open-source para figuras (se for outro)
export AGRCK_PYMOL_MCP=/caminho/.venv/bin/agentic-pymol # opcional
```
Depois, numa pasta de trabalho: `agrck doctor`.

## 5. Contexto mínimo na pasta de trabalho
O `CLAUDE.md` da raiz de um plugin não é carregado. As regras chegam pelas skills. Para ter as 8 regras sempre
visíveis, copie `AGENTS.md` e `CLAUDE.md` do plugin para a pasta de trabalho:
```bash
cp "$(agrck root)/AGENTS.md" "$(agrck root)/CLAUDE.md" .
```

## 6. Atualizar
Mude `version` em `.claude-plugin/plugin.json`, faça push e depois rode:
```bash
claude plugin marketplace update agrck && claude plugin update agrck4moldocking@agrck
```

## 7. Validar antes de publicar
```bash
claude plugin validate . --strict
```

## Desenvolvimento local (sem GitHub)
```bash
claude plugin marketplace add ./AgRCK4MolDocking
claude plugin install agrck4moldocking@agrck
```
