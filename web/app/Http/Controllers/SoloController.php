<?php

namespace App\Http\Controllers;

use App\Models\Song;
use App\Services\AnalyzerClient;
use App\Services\AnalyzerException;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

/** Solos marcados pelo usuário, transcrição assíncrona e tablatura (tudo persistido no analisador, por música). */
class SoloController extends Controller
{
    public function __construct(private AnalyzerClient $analyzer) {}

    private function run(Song $song, string $method, string $suffix, array $body = [], int $ok = 200): JsonResponse
    {
        try {
            $r = $this->analyzer->forward($method, "/v1/songs/{$song->id}$suffix", $body);

            return $r === null ? response()->json(null, 204) : response()->json($r, $ok);
        } catch (AnalyzerException $e) {
            return response()->json(['message' => $e->userMessage], in_array($e->httpStatus, [404, 409, 422], true) ? $e->httpStatus : 502);
        }
    }

    public function index(Song $song): JsonResponse
    {
        return $this->run($song, 'GET', '/solos');
    }

    public function store(Request $request, Song $song): JsonResponse
    {
        $d = $request->validate(['start' => 'required|numeric|min:0', 'end' => 'required|numeric|gt:0', 'category' => 'nullable|string|max:20', 'instrument' => 'nullable|string|max:20']);

        return $this->run($song, 'POST', '/solos', array_filter($d, fn ($v) => $v !== null), 201);
    }

    public function update(Request $request, Song $song, string $solo): JsonResponse
    {
        $d = $request->validate(['start' => 'nullable|numeric|min:0', 'end' => 'nullable|numeric|gt:0', 'category' => 'nullable|string|max:20', 'instrument' => 'nullable|string|max:20']);

        return $this->run($song, 'PATCH', "/solos/$solo", array_filter($d, fn ($v) => $v !== null));
    }

    public function destroy(Song $song, string $solo): JsonResponse
    {
        return $this->run($song, 'DELETE', "/solos/$solo");
    }

    public function transcribe(Request $request, Song $song, string $solo): JsonResponse
    {
        $d = $request->validate(['preprocess' => 'nullable|in:foreground,harmonic,raw', 'tuning' => 'nullable|array|min:4|max:8', 'tuning.*' => 'integer', 'max_fret' => 'nullable|integer|min:5|max:30']);

        return $this->run($song, 'POST', "/solos/$solo/transcribe", array_filter($d, fn ($v) => $v !== null), 202);
    }

    public function tab(Song $song, string $solo): JsonResponse
    {
        return $this->run($song, 'GET', "/solos/$solo/tab");
    }

    public function saveTab(Request $request, Song $song, string $solo): JsonResponse
    {
        $d = $request->validate(['tuning' => 'required|array|min:4|max:8', 'tuning.*' => 'integer', 'max_fret' => 'nullable|integer|min:5|max:30', 'notes' => 'required|array|max:3000']);

        return $this->run($song, 'PUT', "/solos/$solo/tab", $d + ['max_fret' => 22]);
    }

    public function retab(Request $request, Song $song, string $solo): JsonResponse
    {
        $d = $request->validate(['tuning' => 'required|array|min:4|max:8', 'tuning.*' => 'integer', 'max_fret' => 'nullable|integer|min:5|max:30', 'notes' => 'required|array|max:3000']);

        return $this->run($song, 'POST', "/solos/$solo/retab", $d + ['max_fret' => 22]);
    }
}
