<?php

namespace App\Http\Controllers;

use App\Models\Song;
use App\Services\AnalyzerClient;
use App\Services\AnalyzerException;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Validation\ValidationException;
use Inertia\Inertia;
use Inertia\Response as InertiaResponse;
use Symfony\Component\HttpFoundation\StreamedResponse;

class SongController extends Controller
{
    public function __construct(private AnalyzerClient $analyzer) {}

    /** Sincroniza o estado local com o analisador (silencioso se o serviço estiver fora do ar). */
    private function sync(Song $song): bool
    {
        if ($song->isFinal()) {
            return true;
        }
        try {
            $song->applySummary($this->analyzer->summary($song->id));

            return true;
        } catch (AnalyzerException) {
            return false;
        }
    }

    public function index(): InertiaResponse
    {
        $songs = Song::orderByDesc('created_at')->get();
        $songs->each(fn (Song $s) => $this->sync($s));

        return Inertia::render('Songs/Index', [
            'songs' => $songs->map->toFrontend()->values(),
            'maxUploadMb' => config('harmonia.max_upload_mb'),
        ]);
    }

    public function store(Request $request)
    {
        $request->validate([
            'file' => ['required', 'file', 'extensions:mp3,wav', 'max:'.(config('harmonia.max_upload_mb') * 1024)],
            'title' => ['nullable', 'string', 'max:200'],
        ], [
            'file.required' => 'Selecione um arquivo MP3 ou WAV.',
            'file.extensions' => 'Formato não permitido. Envie um arquivo MP3 ou WAV.',
            'file.max' => 'O arquivo excede o tamanho máximo permitido.',
            'file.uploaded' => 'Falha no envio. O arquivo pode exceder o limite do servidor.',
        ]);

        $file = $request->file('file');
        $title = trim((string) $request->input('title')) ?: pathinfo($file->getClientOriginalName(), PATHINFO_FILENAME);

        try {
            $res = $this->analyzer->upload($file, $title);
        } catch (AnalyzerException $e) {
            throw ValidationException::withMessages(['file' => $e->userMessage]);
        }

        Song::create([
            'id' => $res['id'],
            'title' => mb_substr($title, 0, 200),
            'original_filename' => mb_substr($file->getClientOriginalName(), 0, 255),
            'status' => $res['status'] ?? 'pending',
        ]);

        return redirect()->route('songs.show', $res['id']);
    }

    public function show(Song $song): InertiaResponse
    {
        $this->sync($song);

        return Inertia::render('Songs/Show', ['song' => $song->toFrontend()]);
    }

    public function status(Song $song): JsonResponse
    {
        $reachable = $this->sync($song);

        return response()->json(['song' => $song->toFrontend(), 'analyzer_reachable' => $reachable]);
    }

    /** Resultados completos (somente quando a análise terminou). */
    public function data(Song $song): JsonResponse
    {
        try {
            $chords = $this->analyzer->chords($song->id);
            try {
                $raw = $this->analyzer->chordsRaw($song->id)['segments'] ?? null;
            } catch (\Throwable) {
                $raw = null; // análises anteriores à versão com modo detalhado
            }

            return response()->json([
                'chords_raw' => $raw,
                'analysis' => $this->analyzer->analysis($song->id),
                'chords' => $chords['segments'],
                'edited' => $chords['edited'],
                'sections' => $this->analyzer->sections($song->id)['sections'],
                'report' => $this->analyzer->report($song->id),
                'history' => $this->analyzer->history($song->id),
            ]);
        } catch (AnalyzerException $e) {
            return response()->json(['message' => $e->userMessage], $e->httpStatus === 409 ? 409 : 502);
        }
    }

    public function learning(Song $song): JsonResponse
    {
        try {
            return response()->json($this->analyzer->learning($song->id));
        } catch (AnalyzerException $e) {
            return response()->json(['message' => $e->userMessage], 502);
        }
    }

    public function review(Request $request, Song $song): JsonResponse
    {
        $data = $request->validate(['reviewed' => ['required', 'boolean']]);
        try {
            $this->analyzer->setReview($song->id, (bool) $data['reviewed']);

            return response()->json($this->analyzer->learning($song->id));
        } catch (AnalyzerException $e) {
            return response()->json(['message' => $e->userMessage], 502);
        }
    }

    public function saveChords(Request $request, Song $song): JsonResponse
    {
        $data = $request->validate([
            'base_run_id' => ['nullable', 'string', 'max:32'],
            'segments' => ['required', 'array', 'max:5000'],
            'segments.*.start' => ['required', 'numeric', 'min:0'],
            'segments.*.end' => ['required', 'numeric', 'gt:segments.*.start'],
            'segments.*.chord' => ['required', 'string', 'max:16', 'regex:/^(N|[A-G][#b]?[A-Za-z0-9#b+()\/\-]*)$/'],
        ], ['segments.*.chord.regex' => 'Acorde inválido. Use notação como C, F#m, Bb7, Dsus4 ou C/E.']);

        try {
            return response()->json($this->analyzer->saveEdited($song->id, $data['base_run_id'] ?? null, $data['segments']));
        } catch (AnalyzerException $e) {
            return response()->json(['message' => $e->userMessage], 502);
        }
    }

    public function reanalyze(Song $song): JsonResponse
    {
        try {
            $this->analyzer->reanalyze($song->id);
        } catch (AnalyzerException $e) {
            return response()->json(['message' => $e->userMessage], $e->httpStatus === 409 ? 409 : 502);
        }
        $song->update(['status' => 'pending', 'stage' => null, 'error_code' => null, 'error_message' => null]);

        return response()->json(['song' => $song->toFrontend()], 202);
    }

    /** Proxy do áudio com suporte a Range: o arquivo nunca é público. */
    public function audio(Request $request, Song $song): StreamedResponse
    {
        try {
            $r = $this->analyzer->audio($song->id, $request->header('Range'));
        } catch (AnalyzerException $e) {
            abort($e->httpStatus === 404 ? 404 : 502, $e->userMessage);
        }

        $headers = ['Accept-Ranges' => 'bytes', 'Cache-Control' => 'private, no-store'];
        foreach (['Content-Type', 'Content-Length', 'Content-Range'] as $h) {
            if ($r->header($h)) {
                $headers[$h] = $r->header($h);
            }
        }

        return response()->stream(function () use ($r) {
            $body = $r->toPsrResponse()->getBody();
            while (! $body->eof()) {
                echo $body->read(65536);
                flush();
            }
        }, $r->status(), $headers);
    }
}
