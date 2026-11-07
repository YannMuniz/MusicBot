# Harmonia AI

Análise musical automática (tom, acordes, seções) de arquivos MP3/WAV.

## Estado atual
- `analyzer/` — serviço FastAPI (Python): upload validado, fila interna, análise automática (tom, acordes, seções), armazenamento por música, reprocessamento, correções, histórico.
- `web/` — Laravel 13 + Inertia + React (**sem login por enquanto**): upload, histórico, estado do processamento, player sincronizado, tom, seções, transposição, correção de acordes, reprocessamento.
- `db` — PostgreSQL (índice das músicas). Os resultados da análise ficam em `storage/songs/<id>/` (única fonte de verdade).
- `poc/` — prova de conceito original (CLI), preservada. `eval/` — avaliação (mir_eval por tipo/inversões/fragmentação/ambiguidade, comparação por ordem com cifras sem tempo). `training/` — pipeline de fine-tuning **preparado, não executado**. Baixo/inversões (`A/C#`) são detectados a partir do áudio por um detector independente; 6ª/sus2/sus4/9ª **não** são reconhecidas com confiança (ver `docs/avaliacao.md`). `docs/avaliacao.md` — diagnóstico, alternativas e resultados reais.

## Executar
```bash
cp .env.example .env     # preencha: ANALYZER_INTERNAL_TOKEN (openssl rand -hex 32),
                         # DB_PASSWORD e APP_KEY (echo "base64:$(openssl rand -base64 32)")
docker compose up -d --build
```
- Aplicação: **http://localhost:8080** (somente loopback). Documentação da API interna: http://127.0.0.1:8000/docs
- Cada música fica em `storage/songs/<id>/` (não versionado, nunca público; o áudio só sai pelo Laravel, com Range).
- O servidor PHP embutido é para desenvolvimento; produção exigirá nginx/PHP-FPM.

## Aprendizado, solos e tablaturas (rodada 5)
- **Correções → exemplos:** cada correção guarda características acústicas, tipo e origem; músicas que você marca como *revisadas* viram memória de exemplos
  usada (com salvaguardas e auditoria) em OUTRAS gravações. É recuperação de exemplos, **não** retreino do BTC.
- **Solos:** o sistema não afirma onde há solo (a detecção automática de voz/solo não generalizou nos testes): você marca o trecho.
  Transcrição **monofônica** assíncrona (pYIN sobre o primeiro plano) e tablatura de guitarra com digitação plausível, afinação configurável, correção manual e técnicas **inferidas**.
- Detalhes, métricas reais e limitações: `docs/avaliacao.md` (rodada 5).

## Testes
```bash
# Laravel (SQLite em memória; a trava do TestCase aborta se a conexão não for essa)
docker compose run --rm --no-deps --entrypoint "" -e APP_KEY=base64:$(openssl rand -base64 32) \
  -e APP_ENV=testing -e DB_CONNECTION=sqlite -e DB_DATABASE=:memory: web php artisan test
# Transposição (JS, sem dependências extras; em web/)
npm test
# Analisador (Python)
docker build --build-arg DEV=1 -t harmonia-analyzer-dev analyzer
docker run --rm --memory 3g harmonia-analyzer-dev python -m pytest -q
```
Os testes usam áudio **sintetizado** (verdade conhecida por construção). Eles verificam o pipeline e a segurança,
**não medem a precisão em música real**. Para isso use `eval/` com um `.lab` anotado por humanos (`python eval/score_chords.py chords.json ref.lab --detailed`).
Testes de eval e de treino: `docker run --rm -v "$PWD":/work -w /work/eval harmonia-analyzer-dev python -m pytest -q` (e `-w /work/training ... tests`).

## Limitações conhecidas
- Motor BTC: reconhece maj, min, 7, maj7, m7, dim, aug, sus2, sus4, 6, m6, dim7, m7(b5), mM7. **Sem 9ª/11ª/13ª/add/alterados**; baixo/inversão é experimental (campo `inversion`, não altera o acorde). Segmentos ambíguos são marcados (`ambiguous`), com limiares heurísticos.
- `score` dos acordes e `correlation` do tom NÃO são probabilidades calibradas.
- Seções: rótulos neutros; `repeat_group` indica semelhança acústica, não estrofe/refrão/solo.
- Tom único por música (modulações não detectadas).
- Desempenho: ~2 min para 4,5 min de áudio em CPU (a separação harmônica/percussiva domina).
- Fila interna de 1 worker, sem timeout forçado por análise; tarefas pendentes são reenfileiradas ao reiniciar.
- Precisão em música real ainda **não medida**.
