# Lições aprendidas (erros reais de estudos anteriores e a trava que os impede)

| # | Erro cometido | Trava |
|---|---|---|
| 1 | Marca d'água de PyMOL sem licença foi recortada e depois apagada por algoritmo | Proibido. Hook bloqueia; figuras só com PyMOL open-source (`agrck doctor`, manifesto) |
| 2 | Figuras 3D refeitas em ciclo por várias sessões | `agrck attempt ID figura_X` (máx. 2) → parar e perguntar |
| 3 | Interação atribuída ao açúcar quando vinha do anel catecol | Coluna `ligand_fragment` (índices de átomos); o texto cita só essa coluna |
| 4 | "Comprova", "elucida", "validada como bitópica" para um resultado de docking | `agrck lint` + hook pós-edição; revisor independente |
| 5 | Escolha da métrica que favorecia o composto líder | Métrica primária pré-registrada no E0; `agrck audit` mostra todas |
| 6 | Pose do controle ausente numa figura comparativa | `require_objects` no render; manifesto por figura |
| 7 | Logotipos e nome de outra universidade herdados do template LaTeX | `report_check` (strings proibidas); campo `saidas.instituicao` |
| 8 | Numeração de páginas quebrada; refs indefinidas | `report_check` lê o log; inspeção visual de todas as páginas |
| 9 | Controle básico modelado neutro → pose invertida (RMSD 4,7 Å) | Portão E1 exige `microespecie: confirmada` para grupos ionizáveis |
| 10 | RMSD calculado sem simetria deu 3,3 Å em vez de 0,5 Å | Só `rescoring.rmsd_to_reference` (CalcRMS, simetria) |
| 11 | Pose existia no servidor mas não na cópia local | Sincronizar `results/` inteiro antes de analisar/renderizar |
| 12 | Nomes de objeto reservados no PyMOL (`x`, `q`) quebraram seleções | Objetos sempre com prefixo (`lig_`, `rec_`) e seleção `model <nome>` |
| 13 | Fatos não conferidos gravados na memória e repetidos depois | MEMORIA.md aceita só fato com fonte; interpretação fica no relatório |
| 14 | Fenol com pKa ≈ pH do ensaio modelado só neutro sem discutir | Listar grupos ionizáveis no E1 e citar a limitação no relatório |
