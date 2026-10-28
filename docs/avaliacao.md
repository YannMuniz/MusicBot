# Reconhecimento de acordes: diagnóstico, alternativas e avaliação

Data: 2026-10-28. Tudo abaixo foi conferido no código ou medido; o que não foi verificado está marcado **[não verificado]**.

## 1. Diagnóstico do que existe (conferido nos arquivos)
- **Motor:** BTC (Park et al., ISMIR 2019), checkpoint `btc_model_large_voca.pt` (SHA-256 `1673d23f…ab51`), CPU, ~8 s de inferência por música de 4,5 min.
- **Vocabulário real (170 classes):** 12 raízes × 14 qualidades (`maj, min, 7, maj7, m7, dim, aug, sus2, sus4, 6, m6, dim7, m7(b5), mM7`) + `N` + `X`. `X` é suprimido na decodificação. **Não há 9ª/11ª/13ª/add nem baixo/inversão.**
- **Decodificação:** posteriors por quadro (10/108 s) → Viterbi com permanência 0,9 → fusão de trechos < 0,25 s. A grade temporal vem do modelo (CQT em blocos de 10 s, 108 quadros/bloco), não das batidas; sem deriva temporal por construção.
- **Tom não corrige acordes:** só decide a grafia (bemol/sustenido). Não há prior diatônico (propositalmente: ele prejudicaria dominantes secundárias e empréstimos modais, e não foi demonstrado ganho).
- **Fallback:** baseline maj/min (templates + Viterbi por batida) se os pesos faltarem ou `ANALYZER_CHORD_ENGINE=baseline`.
- **Correções do usuário:** `chords.edited.json` (lista inteira, sem proveniência). **Novo:** `corrections.json` (ver §5).
- **Desempenho:** ≈94–134 s por música de 4,5 min; HPSS domina (≈65 s), BTC ≈8 s.
- **Testes:** pytest (sintético), `eval/` (mir_eval), PHPUnit, node:test.

## 2. Alternativas avaliadas
| Opção | Vocabulário | Evidência | Licença | Decisão |
|---|---|---|---|---|
| **BTC large_voca (atual)** | 170 classes, 7ªs, sem extensões/baixo | ISMIR 2019; ChordMini (2026) cita ≈58–63 % em *sevenths* para BTC | código MIT; pesos do repositório original (termos não declarados) | **mantido** |
| ChordMini (2E1D / BTC distilado) | mesmo tipo de vocabulário; README lista "inversões/extensões" como *trabalho futuro* | arXiv 2602.19778 | código MIT; **pesos/dados rotulados sem termos claros**; dados rotulados não distribuídos | não adotado: ganho sobre BTC pequeno e licença dos pesos incerta |
| ChordFormer (arXiv 2502.11840) | vocabulário grande (raiz+tríade+baixo+7ª/9ª/11ª/13ª), 301 acordes segundo o artigo | +2 % frame-wise, +6 % class-wise sobre estado da arte (resumo) | **[não verificado]** se há código/pesos públicos e a licença | **não integrável hoje**; candidato se pesos abertos aparecerem |
| Chordino / NNLS-Chroma | maj, min, 7ª, dim, aug, sus, inversões (baixo) | clássico, sem rede | metadados do plugin indicam **GPL** | não adotado: copyleft e sem ganho demonstrado sobre BTC |
| madmom (chord CRF) | maj/min | – | pesos **[não verificado]** (historicamente CC BY-NC-SA) | não adotado (vocabulário menor, licença) |
| Transcrição de notas (ex.: basic-pitch) para inferir extensões | notas, não acordes | – | **[não verificado]** | não adotado: em mixagem completa as notas de acompanhamento são pouco confiáveis; inventaria extensões |

Conclusão: **nenhum modelo aberto, com pesos utilizáveis e licença clara, cobre extensões e inversões de forma verificada.** Não troquei o motor só por vocabulário maior.

## 3. O que foi implementado (e por quê)
1. **Confiança por segmento** (`p`, `root_p`, `alternatives`, `ambiguous`) a partir das posteriors do BTC. O sistema agora diferencia previsão firme de ambígua (ex.: `Bbmaj7` com p=0,46 e `Bb` como alternativa). Limiares (p<0,5 ou margem<0,25) são **heurísticos, não calibrados**.
2. **Baixo estimado** (`bass`, `inversion`): experimental, informativo; **não altera o nome do acorde** (§4).
3. **Parâmetros e proveniência** gravados em `analysis.json` (`algorithm.parameters`, SHA dos pesos).
4. **Registro de correções** com proveniência (§5) e **pipeline de treino** preparado com travas (§6).
5. **Avaliação detalhada** (`eval/metrics.py`, `score_chords.py --detailed`).

## 4. Resultados reais disponíveis ("O Tempo", Oficina G3, versão BTC)
Referência: cifra do Cifra Club (sem tempos; só ordem). **Uma música; não é medida de acerto por segundo.**
- Ordem dos acordes (raiz): 121 de 122 acordes da cifra encontrados em ordem; 134 segmentos detectados (≈10 inserções); distância de edição 11.
- Ambiguidade: 18 de 134 segmentos marcados ambíguos (rerodada de 2026-10-28), concentrados em `Bbmaj7`/`Bb`, `Gm7`/`Gm`, onde a cifra tem `A#9` e `Gm`.
- Baixo (alinhamento por ordem): o baixo dominante estimado coincide com o da cifra em 18 de 21 acordes com inversão (`F/A`…) e com a fundamental em 81 de 100 acordes sem inversão. A **regra** de decidir "inversão" (baixo ≥ 1,5× a fundamental, nota do acorde) rendeu 7 certas, 14 perdidas, 10 falsas. Por isso `inversion` fica experimental e não muda `chord`. O limiar 1,5 foi fixado antes de olhar os dados; não o ajustei nesta música.
- **Extensões:** `A#9` e `C2` da cifra saem como `Bb/Bbsus2/Bbmaj7` e `C`; o modelo não consegue dizer "9ª".

Nenhuma porcentagem de acerto por segundo foi medida: falta uma referência com tempos (`.lab`).

## 5. Correções como dados de melhoria
`storage/songs/{id}/corrections.json` (sobrevive a reprocessamentos). Por correção: `song_id`, `run_id`, `start`, `end`, `predicted`, `corrected`, `model{name,version,weights_sha256}`, `created_at`, `source` (`ui`), `validation_status` (`unreviewed|accepted|rejected`), `superseded`. Só registra o que **mudou** o acorde previsto; dedup por hash; reedições marcam as antigas como `superseded`. Nada altera outras músicas. `training/export_corrections.py` exporta apenas `accepted` e não `superseded`, descarta sobreposições conflitantes e as lista. **Ainda não há UI para revisar/aceitar**: `validation_status` só muda por edição do arquivo ou API futura.

## 6. Treino próprio: preparado, **não executado**
Ver `training/README.md`. Motivo: não há dados rotulados adequados no projeto (1 música sem tempos). O fine-tuning recusa rodar com < 120 min de áudio anotado em treino ou sem val/test.

## 7. Limitações
- Sem 9ª/11ª/13ª/add/alterados/inversões confiáveis.
- Precisão em música real: **não medida** (nenhuma referência com tempos).
- Probabilidades não calibradas; limiares de ambiguidade heurísticos.
- Tom único por música; ambiguidade F/C já vista.


---
# Rodada 2 — extensões, sus e baixo invertido (música "Estamos de pé")

## Diagnóstico dos erros observados (causa de cada um)
Observações do usuário, **sem tempos nem cifra** (por isso nenhuma taxa de acerto é possível para eles):

| Erro | Causa encontrada no código/dados |
|---|---|
| **A/C#** saía `A` | **Pós-conversão**, não modelo. O harmônico `A` e o baixo `C#` já eram detectados (`inversion` existia no JSON), mas a cifra exibia só o rótulo harmônico. |
| **E6** | **Modelo.** As posteriors do BTC têm massa ≈ 0 em `maj6` em toda a música (nenhum quadro tem `6` como argmax). Nenhuma regra de pós-processamento recupera isso sem evidência nova. A 6ª também é fraca no cromagrama dos trechos `E` (≤ 0,48 das notas do acorde): sem indício de E6 nesses trechos. |
| **D2** | **Modelo + convenção.** `sus2` também tem massa ≈ 0. "D2" é ambíguo em cifras brasileiras (Dsus2 *ou* Dadd9). A 2ª (E) é forte nos `D` (mediana 0,60) mas E é a quinta de A e vaza dos vizinhos: plausível, inconclusivo. |
| **A4** | **Modelo + convenção.** `sus4` tem 3–7 % de massa. Os picos de 4ª em `A` caem nos trechos `A/C#` (vazamento do `D` seguinte): não é evidência de A4. "A4" também é ambíguo (sus4 vs add4). |

Vocabulário **não** é a causa de E6/D2/A4: `maj6`, `sus2` e `sus4` existem nas 170 classes. O BTC simplesmente quase não os prevê aqui.
Pré-processamento: o BTC usa CQT 144 bins/24 por oitava (preserva oitava), mas o modelo só emite rótulos de acorde sem baixo; o cromagrama do sistema (12 classes) descarta oitava, por isso o baixo é um detector à parte.

## Arquitetura adotada (híbrida, incremental; BTC mantido como baseline)
1. **BTC** continua como detector harmônico. Nada foi trocado (ver tabela de alternativas acima; nenhuma tem pesos verificáveis com extensões).
2. **Detector de baixo independente** (`analysis/bass.py`, v2): CQT 36 bins/oitava (C1–C6, mantém oitava); candidatos = fundamentais reais entre E1–G3; harmônicos 2–4 reforçam; votação por quadro dentro do segmento do BTC; só vira inversão se o baixo é nota do acorde, tem ≥ 60 % dos votos, ≥ 50 % dos quadros com voto, e o segmento ≥ 0,4 s. Caso contrário o acorde harmônico é mantido e o motivo fica em `bass.reason` (`root`, `bass_not_in_chord`, `weak_evidence`, `segment_too_short`, `no_bass_energy`).
3. **Representação estruturada** (`analysis/harmony.py`): `model_label` (BTC bruto), `harmonic_label`, `chord` (final, com `/baixo`), `structure{root,quality,intervals,bass,inversion{bass,interval,degree},added}`, `bass`, `evidence.tones`, `possible_additions`.
4. **Evidência de notas de cor** (2ª/4ª/6ª/7ª): medida no cromagrama harmônico e exposta como `possible_additions` (ex.: `D(add9?)`, `D(sus2?)` conforme a terça esteja presente). **Não altera `chord`.**
5. **Interface:** `?` nos segmentos ambíguos, tooltip com probabilidade, alternativas, baixo e notas de cor possíveis; o campo de edição aceita `A/C#`.
6. **Correções:** registram harmonia e baixo separados (`corrected_harmonic`, `corrected_bass`, `predicted_*`, confiança), exportáveis em formato Harte (`corrected_harte`).

## Por que **não** promovi extensões ao rótulo final
Teste do sinal no único material com cifra: `C2` vs `C` em "O Tempo" — 2ª relativa **0,31 vs 0,38 (sem discriminação)**; já `A#9` da cifra teve 0,95 contra ~0,3–0,4 nos acordes simples. Sinal inconsistente e a música com "estamos de pé" não tem referência. Afirmar 6ª/9ª/sus pelo cromagrama seria inventar nota. Por isso ficam como possibilidade sinalizada, e o sistema não apresenta nona como certeza.

## Achado durante os testes: "fundamental virtual"
A primeira versão do baixo (soma harmônica livre) fez falhar um teste antigo: em áudio **sem baixo**, os harmônicos das notas do acorde (`C E G`) produziam uma fundamental virtual (`E3`) e, portanto, `C/E` falso. Corrigido exigindo que a fundamental do candidato exista no áudio e que o grave não seja muito mais fraco que os médios. Há teste de regressão (acorde sem baixo nunca ganha inversão). Isso mostra o risco do método: em gravações com baixo muito fraco ou ausente, o sistema prefere **não** registrar inversão.

## Evaluation protocol
`eval/references/registry.json`: "O Tempo" e "Estamos de pé" são **desenvolvimento** (foram inspecionadas para decidir). **Não existe música de teste independente.** Uma terceira música com `.lab` (ou cifra com tempos) é necessária antes de qualquer afirmação de generalização.

## Resultados reais da rodada 2 (motor final, reprocessado em 2026-10-28)
**"Estamos de pé"** (sem referência; só contagens do próprio sistema, não são acerto):
- 94 segmentos; 6 ambíguos; **4 inversões registradas**: `A/C#` em 70,8 s, 126,0 s e 236,8 s (votos de baixo 94 %, 92 %, 62 %) e `D/A` em 113,2 s (77 %). Os três `A/C#` formam a linha de baixo B–C#–D da cadência `Bm → A/C# → D`. O `D/A` não foi mencionado pelo usuário: **não confirmado**.
- `possible_additions` em 30 dos 94 segmentos (ex.: `D(maj7?)` repetido): **ruidoso** (o C# de A vaza para D). Serve só como dica, nunca altera o acorde; baixa especificidade esperada.
- E6, A4 e D2: **não confirmados nem refutados** (sem tempos/cifra). Nenhum virou rótulo final.

**"O Tempo"** (desenvolvimento, cifra só por ordem): ordem dos acordes inalterada (121/122). Baixo, regra v1 → v2:
| | corretas | perdidas | falsas |
|---|---|---|---|
| v1 (razão ≥1,5× a fundamental, média de energia) | 7 | 14 | 10 |
| v2 (votação + fundamental real) | 4 | 17 | 5 |
O v2 é mais conservador (metade das inversões falsas, mais inversões perdidas: 25 segmentos ficam em `weak_evidence`). O baixo dominante coincidia com o da cifra em 18/21 (v1) e 15/21 (v2) dos acordes com inversão. Limitação provável: a fronteira dos segmentos do BTC não acompanha as mudanças de baixo (um `F` que vira `F/A` dentro do mesmo segmento). **Próxima melhoria:** dividir o segmento nas trocas de baixo.
Arquivos: `eval/results/o_tempo_ordem_cifra.json` (baseline v1) e `o_tempo_ordem_cifra_bass_v2.json`.

## Treino
**Nenhum treino foi executado.** Mudanças desta rodada: regras e pós-processamento (baixo, estrutura, evidência), mais o pipeline de dados/avaliação.

---
# Rodada 3 — cifra de "Estamos de pé" (Marcus Salles) como referência prata

## O que foi feito com a cifra
- Transcrita em `eval/references/estamos_de_pe.chart.json` (97 acordes; ordem das seções conferida contra a detecção: 78 de 80 acordes colapsados em ordem, 97,5 %).
- **Convenções lidas dos diagramas do próprio PDF** (a confirmar de ouvido): `A4 = Asus4` (x02230), `D2 = Dsus2` (xx0230), `E6`, `A/C#`. A avaliação rejeita "D2"/"A4" crus por serem ambíguos; a cifra passa por `resolve`.
- **Alinhamento forçado** (`eval/align_chart.py`): HMM esquerda→direita sobre a posterior de **raiz** do BTC → `estamos_de_pe.silver.lab` (97 acordes colocados, raiz posterior média 0,84). Por usar só a raiz, a qualidade avaliada não é viciada pelo BTC. É referência **prata**: rótulos da cifra, tempos estimados (±0,1–0,5 s), e acordes consecutivos de mesma raiz (`A4 A`, `E6 E`) têm fronteira arbitrária. Por isso a avaliação é **por evento** (`eval/chart_events.py`), não por quadro.

## Resultados por evento (motor atual; música de desenvolvimento)
| Rótulo da cifra | eventos | rótulo exato | só a tríade | na alternativa do modelo |
|---|---|---|---|---|
| A | 25 | 24 | 0 | 0 |
| D | 15 | 15 | 0 | 0 |
| G | 14 | 14 | 0 | 0 |
| E | 6 | 6 | 0 | 0 |
| F#m | 3 | 3 | 0 | 0 |
| Bm | 3 | 2 | 0 | 1 |
| Em7 | 11 | 3 | 5 | 7 |
| **A/C#** | 3 | **3** | 0 | 0 |
| **A4 (Asus4)** | 6 | **0** | 5 | 2 |
| **D2 (Dsus2)** | 5 | **0** | 5 | 0 |
| **E6** | 6 | **0** | 6 | 0 |
Raiz certa em todos os grupos (exceto 1 `Em7` e 1 `A`). **A/C#: 3/3 e nenhuma inversão falsa nos pares alinhados por ordem.** O sistema marcou ainda um `D/A` (113,2 s) que a cifra não lista: dentro da janela `A4 A` (108,8–118,6 s) o sistema produziu `E` e `D/A`; A no baixo com D e E é Asus4, então pode ser o A4 mal lido, mas isso é hipótese (a janela foi forçada a `A` pelo alinhamento por raiz); nenhuma regra foi criada a partir dela.

## Por que não "treinei" um classificador de sus/6ª
1. **Sem sinal no cromagrama:** nos intervalos da cifra, a energia relativa da 2ª em `D2` vs `D` tem AUC 0,48; da 4ª em `A4` vs `A`, 0,41; a 6ª nos grupos `E6` fica abaixo da de tríades. Nenhuma feature simples separa essas classes aqui. A "dica de cor" (`possible_additions`) acertou **0 dos 17** eventos sus/6ª e marcou 30 de 94 segmentos: **tem baixa utilidade** (mantida só como dica, sem alterar o acorde).
2. **Dados:** 17 eventos de uma única gravação. Dividir treino/validação/teste dentro da mesma música vazaria timbre e arranjo.
3. **O pipeline recusa:** `training/data/dev_songs.csv` → manifesto com 6,6 min em 1 música; `finetune.py` respondeu `RECUSADO: dados insuficientes (treino com 6.6 min < 120.0; val/test vazios)`.
**Nenhum treino, nem fine-tuning, foi executado.** O que existe de novo é referência, ferramentas de avaliação e conhecimento de onde o modelo falha.

## Em7 (observação)
`Em7` só 3/11 exatos (7/11 aparecem nas alternativas: o modelo hesita entre `Em` e `Em7`, marcado `ambiguous`). Não criei regra: com 11 eventos de uma música qualquer limiar seria ajuste ao dado de desenvolvimento.

## O que desbloquearia melhoria real
(a) um modelo com vocabulário de 6ª/sus validado e licença clara (ChordFormer, se houver pesos abertos); ou (b) dezenas de músicas anotadas com tempos (≥ 120 min) para fine-tuning; ou (c) dividir segmentos nas trocas de baixo + janela curta, para enxergar os acordes de 1 tempo (`A4`, `E6`), que duram bem menos que os segmentos atuais.

---
# Rodada 4 — excesso de seções e segmentação (caso "Estamos de pé": 31 seções)

## Causa da fragmentação (confirmada no código e nos dados)
- **Não** era "uma seção por mudança de acorde": havia 94 acordes e 31 seções de 8 a 23 s.
- `analysis/sections.py` (versão antiga): picos de novidade de um tabuleiro de Foote com **distância mínima de 8 s**
  (`MIN_SECTION_S`). A 104 bpm isso é ≈ 1 frase de 4 compassos (≈ 9,2 s), logo o detector segmentava em **frases**,
  não em partes estruturais.
- O agrupamento de repetição (`repeat_group`) comparava só a **média** de cada trecho (sem ordem) com limiar 0,4:
  refrões repetidos não casavam (19 grupos para 31 trechos) e nada era compactado.
- Os segmentos de acorde (`decode`: Viterbi + fusão < 0,25 s) estavam saudáveis (mediana 4,4 s); o que parecia "notas
  desnecessárias" eram: (a) **pausas `N` exibidas como chips de acorde**, (b) poucos segmentos curtos de baixa
  confiança. O sistema não detecta notas individuais (o BTC só emite acordes; o baixo é só anotação do segmento).
- Início/fim: o `N` inicial (2,8 s) e final são reais e foram preservados.

## Duas estruturas separadas (agora também no dado persistido)
| | arquivo | conteúdo |
|---|---|---|
| Acordes | `chords.json` (+ `chords.raw.json` modo detalhado) | segmentos com `kind` = `chord`/`rest`, p, alternativas, baixo |
| Seções | `sections.json` | partes neutras: `label` (Parte A…), `repeat_group` (identidade), `occurrence`/`occurrences_total`, `phrases` (camada fina), `progression` |
`chords.raw.json` guarda os segmentos do modelo **antes** da suavização (nada é descartado). Nomes semânticos
(verso/refrão/ponte/solo) **não** são inferidos (`semantic_label` = null): não há evidência confiável (p.ex. detecção de voz).

## Pós-processamento de acordes (`analysis/smoothing.py`)
R1 une vizinhos de mesmo rótulo. R2 absorve "piscadas" (curtas **e** de baixa confiança) só se os dois vizinhos são iguais,
ou há mesma raiz, ou o vizinho está nas 3 alternativas do próprio modelo. R3 absorve pausas `N` < 1 s entre acordes; `N` de
início/fim e longos são preservados. Acorde curto **e confiante** nunca é tocado; nunca se une acorde diferente sem
evidência. Só **somem** fronteiras (nenhuma é criada ou deslocada): duração total e sincronia preservadas.
Limiares (p < 0,65; blip < max(0,5 s, 1 batida); pausa < 1 s) são heurísticas fixadas a priori.

## Segmentação em seções (`analysis/sections.py`, novo)
1. Fronteiras: picos da soma (z-score) de **novidade local** (Foote, janela 8 batidas) e **novidade de repetição**
   (Structural Features, Serrà 2014), distância mínima 16 s. Escolhida por comparação em 4 fontes (2 sintéticas com verdade
   exata + 2 cifras alinhadas): F média de fronteira 0,52 (SF 0,49; Foote sozinho 0,26).
2. Identidade: frases comparadas por **DTW** (preserva a ordem, tolera pequenas diferenças de duração; nos blocos da
   cifra de "Estamos de pé" separou 0 de 32 pares de partes diferentes dos pares da mesma parte, contra ~12 % com a
   comparação de médias), agrupamento por ligação média com corte 0,65.
3. Compactação: a sequência de tipos de frase mais longa que se repete (≥ 2 vezes, até 8 frases) vira uma parte composta
   recorrente; frases idênticas consecutivas (ciclos de uma ponte) viram uma ocorrência; partes compostas repetidas em
   sequência são **duas ocorrências** da mesma parte.
Parâmetros: fronteiras (`KERNEL_BEATS`=8, `SF_DELAY`=4, `SF_FILTER_BEATS`=10, `PEAK_LAMBDA`=1,0, `MIN_SECTION_S`=16) foram
**escolhidos numa pequena grade sobre estas mesmas duas músicas** (viés de seleção: tratar como dado de desenvolvimento);
`GROUP_DISTANCE`=0,65 foi fixado antes do varrimento (fronteira entre "mesma parte" e "parte diferente" observada nos
blocos). Todos ficam registrados em `analysis.json → algorithm.sections`.

## Interface
Visão geral da estrutura (letras coloridas por identidade), seções recolhíveis (com "Recolher/Expandir tudo"),
ocorrência ("Parte B · 2/2", "repete 2×"), pausas como marcador discreto (não acorde), modo **Cifra por seções**,
**Cifra corrida** (sem fragmentação visual) e **Detalhado** (acordes antes da suavização, somente leitura). O resultado
persistido já vem estruturado; nada é só agrupamento visual.

## Antes × depois (referência estrutural PRATA = marcações da cifra alinhadas; só dado de desenvolvimento)
| | Estamos de pé | O Tempo |
|---|---|---|
| seções detectadas / na cifra | 31 → **9** / 9 | 10 → **7** / 11 |
| F de fronteira (±3 s) | 0,21 → **0,50** | 0,32 → **0,50** |
| precisão / revocação (±3 s) | 0,13/0,50 → 0,50/0,50 | 0,33/0,30 → 0,67/0,40 |
| F de fronteira (±0,5 s) | 0,21 → 0,13 | 0,21 → 0,00 |
| F de pares (repetição) | 0,30 → **0,63** | 0,45 → 0,47 |
| mediana (s) / na cifra | 10,4 → 46,1 / 40,6 | 22,1 → 47,1 / 24,7 |
Arquivos: `eval/results/secoes_ANTES_*.json`, `secoes_DEPOIS_*.json`.
Acordes ("Estamos de pé"): 94 → 92 segmentos (2 fronteiras removidas: um `G` de 0,46 s com p=0,63 entre dois `D`, e a fronteira do `D`
seguinte); rótulos que a cifra confirma (A, D, G, E, F#m, Bm, Em7, A/C#) **idênticos** antes/depois; "O Tempo": 134 → 134.
Custo: +≈ 11 s por música de 6,6 min na segmentação.

## O que NÃO melhorou / limitações
- **Fronteiras a ±0,5 s pioraram ou ficaram em 0**: as fronteiras estão em escala de frase/batida suavizada (±3 s), não precisas.
- "O Tempo": 7 seções para 11 da cifra (os pré-refrões e a ponte do solo são curtos e ficaram fundidos; mínimo 16 s).
- Partes curtas (< 16 s, como a Segunda Parte de "Estamos de pé", ≈ 10 s) tendem a se fundir à vizinha.
- Em "Estamos de pé", a Primeira Parte e o início do refrão ficaram na mesma seção (21–87 s; cifra: 21–53 e 53–99).
- A identidade repetida é parcial (F de pares 0,63): o refrão aparece como `Parte B` duas vezes, mas as pontes
  (`Parte D`) só casam em parte. A referência é prata (tempos estimados, ±0,5 s); só duas músicas.
- Mínimo de 16 s e DTW assumem música em compasso regular; música sem pulso claro ou com muita variação de andamento
  pode degradar (não testado).
- Nenhuma música de teste independente: os números acima NÃO são prova de generalização.
