---
name: agrck-estruturas
description: Etapa E1 do docking — obtém e limpa a estrutura PDB, define SMILES com estereoquímica completa e a microespécie de cada ligante no pH do ensaio. Use após o questionário E0 aprovado ou quando o usuário pedir para preparar alvo/ligantes.
---

# E1 — Estruturas e microespécies

1. **Alvo.** Rode `agrck fetch <ID>`, que mostra a resolução e os HETATM. Escolha a cadeia funcional. Mantenha
   em `alvo.manter_het` só os cofatores e metais essenciais. Glicanos e aditivos saem.
2. **Ligantes.** Use o IsomericSMILES do PubChem/ChEMBL com 100% dos estereocentros definidos e grave em
   `estudo.yaml`. Inclua o ligante cocristalizado com `papel: cocristal`; ele é o controle de redocking.
3. **Microespécie no pH do ensaio.** Esta é a armadilha que mais custa.
   - Aminas alifáticas, aminoacridinas e amidinas geralmente ficam protonadas em pH 7–8. Carboxilas ficam desprotonadas.
   - Um fenol com pKa perto do pH do ensaio deve ser registrado como limitação.
   - Discuta cada caso com o usuário e marque `microespecie: confirmada`.
4. Rode `agrck check <ID> E1`. Se falhar, corrija e repita. Não contorne o portão.
5. Mostre a estrutura e o sítio (PyMOL/MCP, se disponível) e peça o "ok". Atualize o `progress.md`.

Execução remota (`execucao.onde: ssh`): sincronize `estudos/<ID>` para o host antes do E2. Use `rsync -a` ou
`scp -r` e nunca copie o `.env`.
