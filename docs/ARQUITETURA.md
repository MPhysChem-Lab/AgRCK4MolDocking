# Arquitetura: as 5 partes do harness

O modelo de linguagem é só o "cérebro". O que torna o agente confiável é o harness em volta dele.

## 1. Loop — uma tarefa, passo a passo
Toda etapa (E0 questionário, E1 estruturas, E2 docking, E3 ranking, E4 interações, E5 figuras, E6 relatório) segue o mesmo ciclo até concluir:

| Passo | No AgRCK |
|---|---|
| PREPARAR | ler `estudos/<ID>/progress.md` e só a skill da etapa |
| PERGUNTAR | só o que falta no `estudo.yaml`, uma pergunta por vez, padrão primeiro |
| CHECAR | `agrck check ID Ex`, portão determinístico; falhou = não avança |
| RODAR | `agrck <comando>`, em segundo plano se for longo, delegado ao executor |
| RETORNAR | mostrar resultado, atualizar `progress.md`, esperar o "ok" do usuário |

## 2. Ferramentas
- `bin/agrck`: CLI único com saída compacta. Evita que o agente monte comandos à mão.
- `pipeline/`: RDKit (preparo), DiffDock NIM (poses), GNINA (minimização + Vina/CNN), PoseBusters (física),
  PDB2PQR/PROPKA + ProLIF (interações), PyMOL open-source (figuras).
- `pipeline/checks/`: travas determinísticas (`fragments`, `claim_lint`, `metric_audit`, `report_check`,
  `figure_check`).
- MCP `pymol` (Agentic PyMOL), para visualização interativa.

## 3. Contexto
- Sempre carregado: `AGENTS.md`, com cerca de 30 linhas (o `CLAUDE.md` só o importa).
- Sob demanda: `skills/agrck-<etapa>/SKILL.md`.
- Referência, lida só se necessário: `docs/PROTOCOLO.md`.

## 4. Memória
| Arquivo | Escopo | Regra |
|---|---|---|
| `estudos/<ID>/progress.md` | sessão → sessão (o "progress.txt") | estado, portões, decisões, histórico |
| `estudos/<ID>/estudo.yaml` | parâmetros do estudo | fonte única dos comandos |
| `memoria/MEMORIA.md` | entre estudos | só fato com fonte verificável |
| `memoria/LICOES.md` | entre estudos | erros reais e a trava correspondente |

Quando a sessão enche, a próxima continua a partir do `progress.md`, sem perguntar de novo.

## 5. Controle
- **Permissões e bloqueios (hooks):** `guard.py` bloqueia contorno de licença, leitura da chave e exclusão
  recursiva de estudos. `lint_report.py` devolve ao agente as afirmações fortes demais a cada edição de
  relatório.
- **Aprovações:** portão por etapa com "ok" explícito do usuário.
- **Limites:** `agrck attempt` (2 por tarefa), timeouts do pipeline, `maxTurns` do executor.
- **Separação de papéis:** quem escreve não aprova (redator ≠ revisor).
