---
name: agrck-relatorio
description: Etapa E6 — escreve o RESUMO.md e, se pedido, o relatório LaTeX/PDF do estudo de docking, com linguagem de hipótese, checagem automática (lint, compilação, template) e revisão independente antes da entrega. Use quando o usuário pedir relatório, resumo, texto de métodos ou PDF.
---

# E6 — Relatório

1. Delegue a redação ao `agrck-redator`. Ele recebe só os caminhos:
   - `estudo.yaml`;
   - `results/metric_audit.md`;
   - `results/interactions/interactions.csv`;
   - as figuras e o `progress.md`.
2. Estrutura do texto:
   - Resumo: contexto, objetivo, método, resultados, conclusões e palavras-chave.
   - 1 Introdução, com a tabela de estruturas 2D.
   - 2 Protocolo.
   - 3 Resultados e Discussão.
   - 4 Conclusões e perspectivas, incluindo as limitações.
   - Referências.
   - Notação formal: ΔG_Vina, LE_Vina, d_sítio. Sem nomes de script, de coluna ou do agente.
3. LaTeX: copie `$(agrck root)/templates/report_latex/` para `estudos/<ID>/relatorio/`. Preencha `instituicao`;
   nunca reaproveite marca de outro template. Compile com `pdflatex`, `bibtex` e `pdflatex` ×2, delegando ao
   `agrck-executor`.
4. Rode `agrck report <ID>` e corrija até zerar. O hook já roda o lint a cada edição.
5. **Revisão independente:** chame o `agrck-revisor`, que nunca é quem escreveu. Ele confere cada número e cada
   atribuição contra os CSVs e grava `relatorio/REVISAO.md`.
   - Corrija os itens `- [ ]` no **relatório** (nunca edite a REVISAO.md) e chame o revisor de novo. O E6 compara
     o `hash_relatorio` com o texto atual: qualquer edição posterior exige nova revisão.
   - Se o usuário revisar pessoalmente, registre `revisor: <nome>` e o veredito dele.
6. Abra e inspecione **todas** as páginas do PDF: figuras, tabelas na margem, numeração e legendas.
7. Entregue com uma lista curta: o que mostra, o que não mostra (limitações) e o que testar experimentalmente.
   Rode `agrck check <ID> E6`. Ele exige relatório não vazio, lint limpo e REVISAO.md aprovada e atual.
