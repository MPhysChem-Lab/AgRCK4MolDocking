# Orquestração de modelos e esforço

Princípio: o modelo caro só raciocina onde o julgamento científico decide o resultado. Tarefas mecânicas vão
para o modelo barato. Escrever e revisar ficam com agentes diferentes.

| Atividade | Quem (Claude Code) | Modelo | Esforço | Codex (equivalente) |
|---|---|---|---|---|
| Entrevista E0, decisões, portões | sessão principal | o da sessão | médio | sessão, `model_reasoning_effort="medium"` |
| Rodar `agrck dock/interactions/figure`, sync, compilar LaTeX, ler logs | `agrck-executor` | haiku | low | `codex exec -c model_reasoning_effort="low" "..."` |
| Tabelas, auditoria de métricas, matriz de interações, specs de figura | `agrck-analista` | sonnet | medium | sessão, `medium` |
| Redação de RESUMO/relatório | `agrck-redator` | sonnet | medium | sessão, `medium` |
| Revisão científica final (afirmações × dados) | `agrck-revisor` | opus | high | `codex exec -c model_reasoning_effort="high"` em sessão nova (contexto limpo) |
| Diagnóstico de bug no pipeline | sessão principal | o da sessão | high | `high` |

## Regras de economia de tokens

1. `AGENTS.md` com cerca de 30 linhas. As skills carregam só na etapa em que são usadas.
2. Ler saídas compactas (`agrck status/check/audit/diagram`), nunca CSVs, PDBs ou SDFs inteiros. Para filtrar,
   usar `grep`/`awk`.
3. Comandos longos rodam em segundo plano, com notificação de término, sem polling.
4. Orçamento de tentativas (`agrck attempt`, padrão 2) evita loops caros.
5. Subagente só para trabalho que não precisa do histórico inteiro. O resultado volta em poucas linhas.
6. Revisor em contexto limpo, nunca na mesma conversa do redator.

## Como fixar modelo e esforço

- **Claude Code:** campos `model` e `effort` no frontmatter de `agents/*.md`. As skills podem fixar `effort`
  para o turno.
- **Codex:** `-c model_reasoning_effort=<low|medium|high>` na linha de comando ou em `~/.codex/config.toml`.
  Para um papel, use uma sessão `codex exec` separada com o prompt do arquivo do agente
  (`agents/agrck-revisor.md`) e o esforço correspondente.
  - O revisor do Codex roda com `AGRCK_ROLE=revisor`, por exemplo
    `AGRCK_ROLE=revisor codex exec -c model_reasoning_effort="high" ...`. Só assim o guard deixa gravar
    `relatorio/REVISAO.md`. No Claude Code, o guard reconhece o subagente `agrck-revisor` pelo `agent_type`.
