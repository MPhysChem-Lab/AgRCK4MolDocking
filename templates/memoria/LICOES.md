# Lições aprendidas (erros reais de estudos anteriores e a trava que os impede)

Cada linha aponta o teste que falha se o erro voltar (`tests/test_lessons.py` confere que todos existem).

| # | Erro cometido | Trava | Teste |
|---|---|---|---|
| 1 | Marca d'água de PyMOL sem licença foi recortada e depois apagada por algoritmo | Hook bloqueia (Claude e Codex); `figure_check` exige PyMOL open-source no manifesto | `test_guard_hook`, `test_figure_check_manifest` |
| 2 | Figuras 3D refeitas em ciclo por várias sessões | `agrck figure` consome o orçamento; `agrck attempt` → PARE | `test_attempt_budget` |
| 3 | Interação atribuída ao açúcar quando vinha do anel catecol | Coluna `ligand_fragment` por índice de átomo; E4 exige fragmento em toda interação | `test_fragments_separate_catechol_from_sugar` |
| 4 | "Comprova", "elucida", "validada como bitópica" para um resultado de docking | `claim_lint` + hook a cada edição + REVISAO.md independente no E6 | `test_claim_lint`, `test_e6_requires_fresh_review` |
| 5 | Escolha da métrica que favorecia o composto líder | Métrica pré-registrada e congelada por hash no E0; `metric_audit` mostra todas | `test_metric_audit_flags_metric_dependence`, `test_prereg_frozen` |
| 6 | Pose do controle ausente numa figura comparativa | `require_objects` no render; manifesto sem objeto vazio | `test_figure_check_manifest` |
| 7 | Logotipos e nome de outra universidade herdados do template LaTeX | `report_check` (strings proibidas, PREENCHER); E0 exige `saidas.instituicao` para LaTeX | `test_report_check_catches_branding_jargon_and_log` |
| 8 | Numeração de páginas quebrada; refs indefinidas | `report_check` lê o log; inspeção visual de todas as páginas (manual) | `test_report_check_catches_branding_jargon_and_log` |
| 9 | Controle básico modelado neutro → pose invertida (RMSD 4,7 Å) | E1: base neutra exige protonar ou `justificativa_neutro`; grupos ionizáveis exigem `microespecie: confirmada` | `test_e1_flags_neutral_base` |
| 10 | RMSD calculado sem simetria deu 3,3 Å em vez de 0,5 Å | Só `rescoring.rmsd_to_reference` (CalcRMS, simetria) | `test_restore_pose_keeps_coordinates_and_charge` |
| 11 | Pose existia no servidor mas não na cópia local | E2 exige a pose selecionada de cada ligante na cópia local | `test_e2_requires_local_poses` |
| 12 | Nomes de objeto reservados no PyMOL (`x`, `q`) quebraram seleções | Prefixos `rec`/`lig_`/`ref_` exigidos no manifesto | `test_figure_check_manifest` |
| 13 | Fatos não conferidos gravados na memória e repetidos depois | Hook recusa fato datado sem `(fonte: ...)` em MEMORIA.md | `test_lint_hook_memory_requires_source` |
| 14 | Fenol com pKa ≈ pH do ensaio modelado só neutro sem discutir | E1 lista grupos ionizáveis e exige decisão; limitação declarada no relatório (revisor) | `test_e1_flags_neutral_base` |
| 15 | Portões pulados ou aprovados sobre resultado antigo | Grafo de portões; comandos recusam etapa sem pré-requisito; reavaliar invalida os dependentes | `test_gate_order_and_invalidation` |
