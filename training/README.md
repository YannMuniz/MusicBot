# Treino próprio (fine-tuning do BTC) — estado: **preparado, não executado**

Nenhum treino foi feito. O sistema usa os pesos originais do BTC. Este diretório contém o pipeline para treinar
quando houver dados rotulados válidos; ele **recusa** treinar sem eles.

## Por que fine-tuning e não treino do zero
O BTC original foi treinado em dezenas de horas de música anotada. Treinar do zero com algumas músicas só produziria
um modelo pior. O fine-tuning (cabeça de saída + últimas camadas) parte do modelo existente e exige menos dados,
mas ainda exige **dados anotados com tempos, com licença que permita o uso**.

## Dados: o que falta
Nada deste repositório serve como treino hoje (1 música, cifra sem tempos). Candidatos públicos, **a verificar
licença e termos de cada um antes de usar [não verificado nesta sessão]**:
- GuitarSet: violão solo, trechos curtos, acordes anotados. Serve para violão; **não basta** para música mixada completa.
- Conjuntos de anotações de acordes de música pop/rock (ex.: Isophonics/Beatles, McGill Billboard): as anotações costumam ser
  livres, mas o **áudio** correspondente geralmente não é redistribuível; é preciso ter o áudio legalmente.
- Correções dos usuários (`corrections.json`): rótulos parciais, só valem após revisão (`accepted`).
Mínimo exigido pelo script: 120 min de áudio anotado em `train`, e `val`/`test` não vazios (valor de segurança, não garantia de qualidade).

## Limite de vocabulário
O fine-tuning mantém as 170 classes. Rótulos com extensão (9ª/11ª/13ª/add) são **reduzidos à qualidade-base** (`vocab.py`),
ou seja, o treino não ensina extensões. Para isso é preciso uma cabeça de saída maior e dados anotados com extensões.

## Fluxo
1. CSV `audio,lab,work_id,source,license` → `python -c "import dataset,json;print(json.dumps(dataset.build_manifest(Path('d.csv'),seed=0)))"` (veja `dataset.py`).
   Divisão por `work_id` (versões/covers da mesma obra nunca se separam), determinística, recusa licença vazia e áudio duplicado.
2. `PYTHONPATH=../analyzer python finetune.py manifest.json --base /opt/models/btc_large_voca.pt --out runs/ft01`
   Gera `btc_finetuned.pt` e `run.json` (SHA dos pesos-base e do manifesto, seed, hiperparâmetros, versões, perdas).
   O melhor epoch é escolhido pela perda de **validação**; o teste não é tocado.
3. Comparar com o original no **teste**:
   `python evaluate_split.py manifest.json --weights /opt/models/btc_large_voca.pt --split test --out base.json`
   `python evaluate_split.py manifest.json --weights runs/ft01/btc_finetuned.pt --split test --out ft01.json`
   Só adote o novo checkpoint se melhorar no teste **sem piorar** acordes simples; custo: `train_seconds` em `run.json`.
4. Para usar: apontar `ANALYZER_BTC_WEIGHTS` para o checkpoint (o SHA dele fica registrado em cada `analysis.json`).

## Testes
`docker run --rm -v "$PWD":/work -w /work/training harmonia-analyzer-dev python -m pytest -q tests`
Verificam o encanamento (mapeamento de vocabulário, divisão sem vazamento, travas, exportação de correções), **não a qualidade musical**.
Um teste de fumaça do treino (áudio sintético, `--allow-small`) rodou sem erro e salvou/recarregou o checkpoint; isso não é evidência de desempenho.
