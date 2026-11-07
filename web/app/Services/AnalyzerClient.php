<?php

namespace App\Services;

use Illuminate\Http\Client\ConnectionException;
use Illuminate\Http\Client\PendingRequest;
use Illuminate\Http\Client\Response;
use Illuminate\Http\UploadedFile;
use Illuminate\Support\Facades\Http;

/** Cliente HTTP do serviço interno de análise (Python/FastAPI). */
class AnalyzerClient
{
    private function http(?int $timeout = null): PendingRequest
    {
        $cfg = config('harmonia.analyzer');

        return Http::baseUrl(rtrim($cfg['url'], '/'))
            ->withHeaders(['X-Internal-Token' => $cfg['token']])
            ->acceptJson()
            ->timeout($timeout ?? $cfg['timeout']);
    }

    /** @throws AnalyzerException */
    private function call(callable $fn): Response
    {
        try {
            $r = $fn();
        } catch (ConnectionException) {
            throw new AnalyzerException('O serviço de análise está indisponível. Tente novamente em instantes.', 503, 'analyzer_unavailable');
        }
        if ($r->successful()) {
            return $r;
        }
        $detail = $r->json('detail');
        $code = is_array($detail) ? ($detail['code'] ?? null) : null;
        $msg = is_array($detail) ? ($detail['message'] ?? null) : (is_string($detail) ? $detail : null);
        if ($r->status() === 401) {
            $msg = 'Falha de autenticação com o serviço de análise (verifique ANALYZER_INTERNAL_TOKEN).';
        }
        throw new AnalyzerException($msg ?? 'Erro inesperado no serviço de análise.', $r->status(), $code);
    }

    public function upload(UploadedFile $file, ?string $title): array
    {
        return $this->call(fn () => $this->http(config('harmonia.analyzer.upload_timeout'))
            ->attach('file', fopen($file->getRealPath(), 'r'), $file->getClientOriginalName())
            ->post('/v1/songs', array_filter(['title' => $title])))->json();
    }

    public function summary(string $id): array
    {
        return $this->call(fn () => $this->http()->get("/v1/songs/$id"))->json();
    }

    public function analysis(string $id): array
    {
        return $this->call(fn () => $this->http()->get("/v1/songs/$id/analysis"))->json();
    }

    public function chords(string $id): array
    {
        return $this->call(fn () => $this->http()->get("/v1/songs/$id/chords"))->json();
    }

    /** Segmentos do modelo antes do pós-processamento temporal (modo detalhado); 409 em análises antigas. */
    public function chordsRaw(string $id): array
    {
        return $this->call(fn () => $this->http()->get("/v1/songs/$id/chords/raw"))->json();
    }

    public function learning(string $id): array
    {
        return $this->call(fn () => $this->http()->get("/v1/songs/$id/learning"))->json();
    }

    public function setReview(string $id, bool $reviewed): array
    {
        return $this->call(fn () => $this->http()->post("/v1/songs/$id/review", ['reviewed' => $reviewed]))->json();
    }

    public function sections(string $id): array
    {
        return $this->call(fn () => $this->http()->get("/v1/songs/$id/sections"))->json();
    }

    public function report(string $id): string
    {
        return $this->call(fn () => $this->http()->get("/v1/songs/$id/report"))->body();
    }

    public function history(string $id): array
    {
        return $this->call(fn () => $this->http()->get("/v1/songs/$id/history"))->json('runs', []);
    }

    public function saveEdited(string $id, ?string $baseRunId, array $segments): array
    {
        return $this->call(fn () => $this->http()->put("/v1/songs/$id/chords/edited", [
            'base_run_id' => $baseRunId,
            'segments' => $segments,
        ]))->json();
    }

    public function reanalyze(string $id): array
    {
        return $this->call(fn () => $this->http()->post("/v1/songs/$id/reanalyze"))->json();
    }

    /** Repasse genérico (usado pelos endpoints de solos/tablatura; o analisador valida o corpo). */
    public function forward(string $method, string $path, array $body = []): ?array
    {
        $r = $this->call(fn () => $this->http()->send($method, $path, $body === [] ? [] : ['json' => $body]));

        return $r->status() === 204 ? null : $r->json();
    }

    /** Resposta em stream (suporta Range) para o player. */
    public function audio(string $id, ?string $range): Response
    {
        return $this->call(fn () => $this->http(120)
            ->withOptions(['stream' => true])
            ->withHeaders(array_filter(['Range' => $range]))
            ->get("/v1/songs/$id/audio"));
    }
}
