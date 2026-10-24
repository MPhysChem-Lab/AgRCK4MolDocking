---
name: agrck-interacoes
description: Etapa E4 — mapeia interações proteína-ligante (receptor protonado PROPKA + ProLIF com critério de distância e ângulo), atribui cada interação ao fragmento do ligante (anel, açúcar, substituinte) e monta a matriz resíduo × ligante. Use quando o usuário pedir interações, diagramas 2D ou explicação de por que um composto é ativo.
---

# E4 — Interações e fragmentos

1. Rode `agrck interactions <ID>`, que cobre todos os ligantes. Ele gera:
   - `results/interactions/interactions.csv`, com a coluna `ligand_fragment`;
   - `<lig>_fragments.json`, que liga cada rótulo aos átomos e ao SMILES do fragmento.
2. **Confira os rótulos:** abra `<lig>_fragments.json` e veja qual SMILES corresponde a cada `anel_k`. Para
   nomes legíveis, defina `fragmentos` (SMARTS) no `estudo.yaml` e rode de novo.
3. Para cada pose escolhida, rode `agrck diagram <ID> <ligante> <pose>`. A saída lista
   `resíduo tipo distância ângulo <- fragmento`.
4. **Regras de atribuição:**
   - Cada frase do tipo "o grupo X interage com Y" precisa citar uma linha do CSV.
   - Proximidade geométrica sem interação tipificada deve ser dita como "proximidade", não como ligação.
   - Ligação de H exige distância **e** ângulo D–H···A.
   - Tracejado do PyMOL não é evidência.
5. Monte a matriz resíduo × ligante, agrupada por sub-sítio, com tipo, distância e ângulo. Destaque o que
   diferencia ativos de inativos. Se nada diferencia, diga isso.
6. Rode `agrck check <ID> E4`. Delegue a montagem da tabela ao `agrck-analista`.
