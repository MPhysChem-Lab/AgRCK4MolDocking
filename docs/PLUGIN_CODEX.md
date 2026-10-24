# Instalar como plugin no OpenAI Codex

O Codex lê o marketplace em `.agents/plugins/marketplace.json` (marketplace `agrck`) e o manifesto em
`plugin.json` / `.codex-plugin/plugin.json`. O plugin entrega as 6 skills e os hooks
(`hooks/hooks.codex.json`, caminhos via `${PLUGIN_ROOT}`). O script do passo 3 cuida do CLI e do `AGENTS.md`
na pasta de trabalho, e serve de alternativa para instalar os hooks em versões do Codex sem hooks de plugin.

## 1. Acesso ao repositório privado
O Codex usa o git da máquina. Use SSH com chave cadastrada no GitHub, ou HTTPS com credential helper
(`gh auth login`).

## 2. Marketplace e plugin
```bash
codex plugin marketplace add git@github.com:fatioleg/AgRCK4MolDocking.git     # ou: fatioleg/AgRCK4MolDocking
codex plugin marketplace list
```
No Codex: `/plugins`, aba **AgRCK4MolDocking**, selecione `agrck4moldocking` e instale com Espaço. Abra uma
sessão nova. As skills aparecem em `/skills` e são chamadas com `$agrck-iniciar`.

Sem sistema de plugins (versões antigas), copie as skills:
```bash
mkdir -p ~/.agents/skills && cp -r AgRCK4MolDocking/skills/agrck-* ~/.agents/skills/
```

## 3. CLI, AGENTS.md e hooks (script)
```bash
git clone git@github.com:fatioleg/AgRCK4MolDocking.git ~/AgRCK4MolDocking
sh ~/AgRCK4MolDocking/scripts/install_codex.sh            # pergunta antes de alterar ~/.codex
```
O script:
- liga `agrck` em `~/.local/bin`; o launcher resolve o symlink;
- copia `AGENTS.md` para a pasta de trabalho, se não existir;
- opcionalmente (pergunta antes) grava os mesmos hooks em `~/.codex/hooks.json` com caminhos absolutos.

Em todos os casos, aprove os hooks no Codex com `/hooks`, porque hooks não gerenciados precisam de confiança.

## 4. MCP do PyMOL (opcional)
Em `~/.codex/config.toml`:
```toml
[mcp_servers.pymol]
command = "/caminho/.venv/bin/agentic-pymol"
startup_timeout_sec = 30
tool_timeout_sec = 300
```

## 5. Modelo e esforço por atividade
O Codex não fixa modelo por subagente como o Claude Code. Use o esforço por sessão (ver
[ORQUESTRACAO.md](ORQUESTRACAO.md)):
```bash
codex -c model_reasoning_effort="medium"                       # sessão de trabalho
codex exec -c model_reasoning_effort="low"  "agrck dock ID"    # tarefa mecânica
codex exec -c model_reasoning_effort="high" "$(cat ~/AgRCK4MolDocking/agents/agrck-revisor.md) Revise estudos/ID/relatorio"
```

## Limitações conhecidas
- O formato de plugin do Codex é recente. Se `/plugins` não listar o marketplace, use o caminho das skills
  copiadas (passo 2) mais o script (passo 3). O agente funciona igual.
- O `AGENTS.md` é lido da raiz do repositório git até a pasta atual. Mantenha-o curto (limite de 32 KiB somando
  todos).
