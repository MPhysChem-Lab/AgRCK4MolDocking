---
name: agrck-docking
description: Etapas E2–E3 — roda o docking (DiffDock + minimização GNINA + PoseBusters) com os parâmetros do estudo e audita o ranking (redocking, poses no sítio, todas as métricas). Use após o portão E1 ou quando o usuário pedir para rodar/ranquear o docking.
---

# E2 — Docking

1. `agrck doctor` precisa passar. A chave fica no `.env` e nunca é lida nem exibida.
2. Confira o comando com `agrck dock <ID> --print`. Depois rode `agrck dock <ID>` **em segundo plano** e
   delegue o acompanhamento ao `agrck-executor`.
   - Tempo típico: cerca de 1–3 min por ligante com 30 poses, minimização em CPU.
   - Não consulte em loop. Aguarde a notificação de término.
3. Remoto: `ssh <host> 'cd <dir_remoto> && bin/agrck dock <ID>'`. Ao terminar, traga a pasta `results/` **inteira**
   (`rsync -a`) antes de analisar ou renderizar.
4. Rode `agrck check <ID> E2`.

# E3 — Ranking auditado

1. Rode `agrck check <ID> E3`. Ele confere:
   - redocking ≤ 2 Å;
   - poses dentro do sítio;
   - a auditoria de métricas.
2. **Redocking > 2 Å.** Veja em `results/poses.csv` se alguma pose amostrada ficou ≤ 2 Å.
   - Se sim, foi falha de **seleção**. Se não, foi falha de **amostragem**.
   - Suspeite primeiro da protonação do controle e conte isso ao usuário.
3. Apresente a tabela de `results/metric_audit.md` **inteira**: Vina, CNNaffinity, CNNscore, LE e d_sítio.
   - Diga qual é a métrica primária pré-registrada.
   - Se a posição do líder depende da métrica, diga isso no texto.
   - Diferenças de Vina < 1 kcal/mol não discriminam.
4. Pergunte quais ligantes e poses detalhar no E4/E5. Sugira o líder, o melhor inativo e o controle.
5. Atualize o `progress.md`. Grave na `MEMORIA.md` só o RMSD validado, com a fonte.

Unidades:
- Vina: kcal/mol, mais negativo é melhor. Não é ΔG experimental.
- CNNaffinity: pK previsto.
- CNNscore: confiança da pose, de 0 a 1.
- Confiança do DiffDock: não é afinidade.
