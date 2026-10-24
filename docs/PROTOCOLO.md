# Protocolo científico (referência; leia só a seção necessária)

## Por que este fluxo
- DiffDock (difusão em SE(3)) amostra o espaço global, mas gera choques e tensões (Buttenschoen 2024).
- A minimização local no GNINA e o PoseBusters corrigem e filtram essas poses.
- Vina (empírico) e CNN (GNINA) dão escores complementares.
- ProLIF, em receptor protonado com PROPKA3, tipifica as interações por distância e ângulo.

## E1 — Curadoria
- **Receptor.** Mantenha só:
  - a cadeia funcional;
  - os cofatores e metais essenciais (`keep_het`);
  - **uma** cópia do ligante cocristalizado, a do sítio.

  Retire glicanos de superfície (`NAG`, `FUC`, `BMA`, `MAN`), aditivos e cópias da unidade assimétrica. Todo
  HETATM com ≥ 6 átomos pesados vira referência de sítio. Anote as águas em ponte (o DiffDock não as usa) para
  a discussão.
- **Ligantes.**
  - Use IsomericSMILES com todos os estereocentros definidos.
  - Registre N_heavy, MW, cLogP, TPSA, N_rot e os alertas PAINS/aceitadores de Michael.
  - Inclua o cocristal, cuja conectividade é casada pelos 14 primeiros caracteres da InChIKey.
- **Microespécie no pH do ensaio.** O pipeline usa o SMILES como foi dado e não reprotona.
  - Aminas alifáticas, aminoacridinas e amidinas (pKa 8–10) entram catiônicas.
  - Ácidos carboxílicos (pKa 3–5) entram aniônicos.
  - Se pKa ≈ pH ± 1, modele as duas formas ou declare a limitação.
  - Sem `[NH+]`, o ProLIF não detecta cátion–π, ponte salina nem ligação de H doadora.

## E2 — Amostragem e refinamento
- 30 poses por ligante, mais `--minimize` (GNINA, receptor rígido).
- As respostas do DiffDock ficam em cache por hash.
- As ordens de ligação e as cargas são restauradas pelo RDKit antes da minimização.

## E3 — Os 4 pilares de qualidade
1. **Redocking.** RMSD com simetria, sem realinhamento, deve ser ≤ 2 Å. Se passar disso, diferencie falha de
   seleção (alguma pose ≤ 2 Å foi amostrada) de falha de amostragem. Discuta holo × cross-docking.
2. **Física.** Relate a fração aprovada no PoseBusters e a mediana do deslocamento na minimização. Separe:
   - choques intermoleculares (impedimento estérico);
   - tensão intramolecular (planaridade, energia interna).
3. **Escores.**
   - CNNscore (0–1): confiança da pose.
   - CNNaffinity ± variância: pK previsto. Variância alta indica fora do domínio de treino.
   - Vina: kcal/mol.
   - LE_Vina = −Vina/N_heavy. Valor ≥ 0,30 é eficiente; serve para corrigir o viés de tamanho.
   - Spearman entre CNN e Vina.
   - Métrica primária **pré-registrada**; todas relatadas.
4. **Topologia.**
   - d_sítio (centroide até a referência). Pose de superfície é a armadilha do docking cego.
   - Convergência: N poses válidas com d ≤ 6 Å, de 30.
   - Em gargantas (AChE, BChE, CYP, HDAC), classifique: catalítico, periférico ou dual-site. "Dual-site" é
     hipótese e exige ocupação simultânea demonstrada pelas interações.
   - Com nucleófilo catalítico e eletrófilo no ligante, meça d(Nu···C) ≤ 3,5–4,0 Å.

## E4 — Interações
- O PROPKA3 define His (HID/HIE/HIP), Asp, Glu, Lys e Cys no pH do ensaio. Metais e cofatores ficam de fora do
  PDB2PQR; meça-os no PyMOL.
- Monte a matriz resíduo × ligante por sub-sítio, com tipo, distância, ângulo e **fragmento** do ligante.

## E5 — Figuras
- Use PyMOL open-source. Em cavidades profundas, cartoon semitransparente com resíduos coloridos por sub-sítio
  e uma legenda.
- O tracejado do PyMOL indica contato **putativo**. A ligação de H confirmada vem do E4.
- Figuras úteis:
  - redocking × cristal;
  - líder × aglicona ou análogo;
  - planar × saturado/volumoso.

## E6 — Relatório
- Escreva texto de métodos com as versões de `metadata.json`.
- Limitações a declarar sempre:
  - receptor rígido;
  - sem águas explícitas;
  - escores semiquantitativos;
  - microespécie;
  - ausência de dinâmica e energia livre. O próximo passo é MD + MM-GBSA.

## Referências
1. Corso G. et al. DiffDock. ICLR 2023. arXiv:2210.01776 · Corso G. et al. DiffDock-L. ICLR 2024. arXiv:2402.18396
2. Buttenschoen M., Morris G. M., Deane C. M. PoseBusters. *Chem. Sci.* 2024, 15, 3130. doi:10.1039/d3sc04185a
3. McNutt A. T. et al. GNINA 1.3. *J. Cheminform.* 2025, 17, 28. doi:10.1186/s13321-025-00973-x · GNINA 1.0. *J. Cheminform.* 2021, 13, 43
4. Riniker S., Landrum G. A. ETKDG. *J. Chem. Inf. Model.* 2015, 55, 2562. doi:10.1021/acs.jcim.5b00654
5. Bouysset C., Fiorucci S. ProLIF. *J. Cheminform.* 2021, 13, 72. doi:10.1186/s13321-021-00548-6
6. Jurrus E. et al. PDB2PQR/APBS. *Protein Sci.* 2018, 27, 112 · Olsson M. H. M. et al. PROPKA3. *JCTC* 2011, 7, 525
7. Golden J. R., Kiefl E. Agentic PyMOL. *The Stacks* 2026. doi:10.57844/arcadia-gsbx-phd2
