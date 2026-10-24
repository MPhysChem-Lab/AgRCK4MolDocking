# AgRCK4MolDocking

Agente de docking molecular para **Claude Code** e **OpenAI Codex**. Ele conduz um pesquisador do alvo ao
relatório, em etapas com portões automáticos:

```
E0 questionário → E1 estruturas/microespécies → E2 DiffDock + GNINA + PoseBusters → E3 ranking auditado
→ E4 interações ProLIF com fragmentos → E5 figuras 3D (PyMOL open-source) → E6 relatório revisado
```

Nasceu do pipeline MiniDock. A diferença está nas travas: cada erro cometido num estudo real virou uma
checagem automática. A lista completa está em `templates/memoria/LICOES.md`. Exemplos:

| Erro real | Trava |
|---|---|
| Marca d'água de PyMOL sem licença foi apagada | hook bloqueia; figuras só com PyMOL open-source |
| Interação atribuída ao açúcar em vez do catecol | coluna `ligand_fragment` calculada por índice de átomo |
| "Comprova", "elucida" para um resultado de docking | `agrck lint` + hook a cada edição + revisor independente |
| Escolher a métrica que favorece o composto líder | métrica primária pré-registrada + `agrck audit` |
| Figuras refeitas em ciclo | `agrck attempt` (máx. 2) → para e pergunta |

## Arquitetura (as 5 partes de um harness)

| Parte | Onde está |
|---|---|
| **Loop** | Preparar → Perguntar → Checar → Rodar → Retornar, por etapa (`AGENTS.md`) |
| **Ferramentas** | `bin/agrck` (CLI único) + `pipeline/` + MCP do PyMOL (`.mcp.json`) |
| **Contexto** | `AGENTS.md` curto; uma skill por etapa (`skills/`), carregada só quando necessária |
| **Memória** | `estudos/<ID>/progress.md` (sessão), `memoria/MEMORIA.md` (fatos com fonte), `memoria/LICOES.md` |
| **Controle** | hooks (`hooks/`), portões `agrck check`, orçamento de tentativas, subagentes com modelo e esforço fixos |

Detalhes em [docs/ARQUITETURA.md](docs/ARQUITETURA.md) e [docs/ORQUESTRACAO.md](docs/ORQUESTRACAO.md).

## Painel de acompanhamento (specboard)

`agrck board ID --open` abre um painel HTML com:
- **Você está aqui:** a etapa atual.
- **Mapa:** E0–E6 com dependências.
- **Progresso:** quanto do estudo já passou nos portões.

O painel usa o renderizador do [specboard](https://github.com/fatioleg/specboard), copiado em `vendor/specboard`. Ele
é **só visualização**:
- é regenerado sozinho a cada `agrck check` ou reabertura de portão;
- não tem travas, hooks nem comandos de verificação;
- apagá-lo não muda nada no estudo.

Nele, "verificado" significa portão do `agrck` aprovado.

## Instalação

- Ambiente científico: [docs/INSTALACAO.md](docs/INSTALACAO.md).
- Plugin no Claude Code: [docs/PLUGIN_CLAUDE_CODE.md](docs/PLUGIN_CLAUDE_CODE.md).
- Plugin no Codex: [docs/PLUGIN_CODEX.md](docs/PLUGIN_CODEX.md).

Resumo (repositório privado; o `gh auth login` precisa já estar feito):

```bash
# Claude Code
claude plugin marketplace add fatioleg/AgRCK4MolDocking
claude plugin install agrck4moldocking@agrck
# Codex
codex plugin marketplace add git@github.com:fatioleg/AgRCK4MolDocking.git   # depois: /plugins no codex
```

## Uso

Numa pasta de trabalho vazia, abra o Claude Code ou o Codex e diga *"quero iniciar um novo estudo de docking"*.
O agente roda a entrevista E0 (`agrck-iniciar`) e cria `estudos/<ID>/`. Comandos diretos:

```bash
agrck doctor            # ambiente
agrck new ID            # novo estudo
agrck status            # onde cada estudo parou
agrck check ID E3       # portão automático da etapa
```

## Estrutura

```
AGENTS.md                     contexto mínimo (Codex; cópia em templates/workspace com CLAUDE.md)
skills/agrck-*/SKILL.md       uma skill por etapa (carregada sob demanda)
agents/agrck-*.md             executor (haiku), analista e redator (sonnet), revisor (opus)
hooks/                        guard (licença, chave, exclusão) e lint de relatório
bin/agrck                     CLI
pipeline/                     run.py, preparation, rescoring, interactions, estilos/, checks/
templates/                    questionário, progress.md, memória inicial, relatório LaTeX
tests/  examples/3PTB/        testes (tripsina + benzamidina, dados públicos)
```

Validação científica do pipeline: redocking 3PTB e testes em `tests/`. O docking gera hipóteses estruturais e
não substitui o ensaio experimental.

## Limitações conhecidas

- As travas de shell são regex. Elas pegam os caminhos comuns e acidentais, mas um agente determinado a
  contorná-las consegue. A defesa final é a revisão independente mais o "ok" humano em cada portão.
- Execução remota: se `run.py` for rodado à mão no servidor, os portões locais só reabrem no próximo
  `agrck dock`/`check` local. Prefira sempre `agrck dock`.
- O E6 confere que o relatório menciona a palavra "emenda" quando há emendas, não o conteúdo de cada uma.
  O revisor confere o resto.
- O painel (specboard) mostra os portões automáticos como "verificado". O "ok" do usuário fica registrado na
  conversa e em `progress.md`, não no painel.
