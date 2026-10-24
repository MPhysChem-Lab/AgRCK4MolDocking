---
name: agrck-iniciar
description: Inicia ou retoma um estudo de docking molecular (etapa E0) — entrevista inicial em blocos com o pesquisador, cria estudos/<ID>/estudo.yaml e pré-registra a métrica primária. Use quando o usuário quiser começar um docking, um novo alvo/série de ligantes, ou disser "novo estudo".
effort: low
---

# E0 — Questionário inicial

Objetivo: preencher `estudos/<ID>/estudo.yaml` com o mínimo de perguntas. Cada pergunta traz uma sugestão
padrão e a opção recomendada vem primeiro. Pule o que o usuário já informou. Se ele colou um questionário
preenchido, use-o e pergunte só o que faltar.

1. Rode `agrck status`. Se houver estudo aberto, pergunte se quer continuá-lo antes de criar outro.
2. Peça um nome curto e rode `agrck new <ID>`.
3. Pergunte em **4 blocos**. Use a ferramenta de perguntas com opções, no máximo 4 perguntas por chamada.

| Bloco | Pergunta | Padrão sugerido |
|---|---|---|
| A. Objetivo | Qual é o objetivo? | explicar a SAR de dados experimentais |
| | Para quem é o resultado? | pesquisador |
| | Que saída você quer? | relatório Markdown + figuras 3D/2D |
| B. Alvo | Enzima, organismo do ensaio e código PDB? | estrutura holo de melhor resolução, mesmo organismo |
| | Há cofator ou metal essencial? Quais resíduos importam? | levantar no PDB e na literatura |
| | pH do ensaio? | 7,4 (Ellman AChE/BChE: 8,0) |
| C. Ligantes | Lista (nome, SMILES/CID) com a atividade medida | — (obrigatório) |
| | Controle positivo do ensaio? E o ligante cocristalizado? | incluir os dois |
| | Qual é o composto mais ativo (líder)? | o de maior atividade |
| D. Protocolo | Poses e minimização? | 30 poses + minimizar |
| | Métrica primária (pré-registro, ANTES dos resultados)? | `cnn_score` dentro do sítio |
| | Onde rodar (local / ssh)? | onde o `agrck doctor` passar |

4. Explique o pré-registro em uma frase: "fixamos a métrica antes de ver os números para não escolher a que
   favorece o composto que queremos". Avise também que todas as métricas serão relatadas.
5. Grave as respostas em `estudo.yaml`. Rode `agrck check <ID> E0` até passar.
6. Mostre um resumo de 5 linhas do plano e peça o "ok" explícito antes do E1. Atualize "Estado" no `progress.md`.

Se o usuário for leigo, defina cada termo na primeira vez (pose, sítio, redocking, pKa).
