---
name: agrck-figuras
description: Etapa E5 — figuras 3D didáticas de poses de docking com PyMOL open-source (redocking sobreposto ao cristal, comparação ativo × inativo, anatomia do sítio), com manifesto e limite de tentativas. Use quando o usuário pedir figuras 3D, imagens de poses ou sobreposições.
---

# E5 — Figuras 3D

**Proibido** remover, recortar, mascarar ou pintar por cima de marca d'água ou aviso de licença. Se o PyMOL
disponível carimba "evaluation", pare e instale o open-source: `conda install -c conda-forge pymol-open-source`
ou `pip install pymol-open-source-whl`. Aponte `AGRCK_PYMOL_PYTHON` para esse Python.

1. Para cada figura, escreva uma especificação `estudos/<ID>/figuras/<nome>.yaml`. O formato está no topo de
   `$(agrck root)/pipeline/estilos/render_figure.py`. Use:
   - só poses minimizadas (`pose_NN_min.sdf`);
   - em `contatos`, só pares confirmados pelo ProLIF (E4);
   - a legenda com o valor do CSV (ex.: RMSD).
2. Rode `agrck figure <ID> <spec.yaml>`. Ele exige objetos não vazios, grava `figuras_manifest.json` e conta
   as tentativas.
3. Abra a imagem e confira: todos os ligantes da legenda estão visíveis? Os rótulos estão legíveis? Nada está
   cortado?
4. Ajustes: no máximo 2 tentativas por figura. Na 3ª, `agrck attempt` devolve PARE. Mostre a melhor versão e
   pergunte o que mudar.
5. Rode `agrck check <ID> E5`.

Figuras recomendadas:
- redocking: cristal × pose;
- anatomia do sítio com sub-sítios coloridos e legenda;
- sobreposição do líder × análogo inativo;
- controle do ensaio.

Em cavidades profundas, use cartoon semitransparente (já é o padrão), não superfície opaca.
