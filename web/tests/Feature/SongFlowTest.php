<?php

namespace Tests\Feature;

use App\Models\Song;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\Client\Request;
use Illuminate\Http\UploadedFile;
use Illuminate\Support\Facades\Http;
use Tests\TestCase;

class SongFlowTest extends TestCase
{
    use RefreshDatabase;

    private const ID = 'a1b2c3d4e5f60718293a4b5c6d7e8f90';

    protected function setUp(): void
    {
        parent::setUp();
        config([
            'harmonia.analyzer.url' => 'http://analyzer.test',
            'harmonia.analyzer.token' => 'secret-token',
        ]);
    }

    private function song(array $attrs = []): Song
    {
        return Song::create(array_merge([
            'id' => self::ID, 'title' => 'Minha música', 'original_filename' => 'minha.mp3', 'status' => 'pending',
        ], $attrs));
    }

    public function test_upload_forwards_file_with_token_and_creates_song(): void
    {
        Http::fake(['analyzer.test/v1/songs' => Http::response(['id' => self::ID, 'status' => 'pending'], 202)]);

        $res = $this->post('/songs', ['file' => UploadedFile::fake()->create('Minha Música.mp3', 500, 'audio/mpeg')]);

        $res->assertRedirect("/songs/".self::ID);
        $this->assertDatabaseHas('songs', ['id' => self::ID, 'title' => 'Minha Música', 'status' => 'pending']);
        Http::assertSent(fn (Request $r) => $r->hasHeader('X-Internal-Token', 'secret-token') && $r->url() === 'http://analyzer.test/v1/songs');
    }

    public function test_upload_rejects_wrong_extension_without_calling_analyzer(): void
    {
        Http::fake();
        $this->post('/songs', ['file' => UploadedFile::fake()->create('virus.exe', 10)])->assertSessionHasErrors('file');
        $this->post('/songs', [])->assertSessionHasErrors('file');
        Http::assertNothingSent();
        $this->assertDatabaseCount('songs', 0);
    }

    public function test_analyzer_validation_error_is_shown_to_user(): void
    {
        Http::fake(['analyzer.test/v1/songs' => Http::response(['detail' => ['code' => 'too_short', 'message' => 'Áudio muito curto (mínimo 5s).']], 422)]);
        $res = $this->post('/songs', ['file' => UploadedFile::fake()->create('a.mp3', 10)]);
        $res->assertSessionHasErrors(['file' => 'Áudio muito curto (mínimo 5s).']);
        $this->assertDatabaseCount('songs', 0);
    }

    public function test_analyzer_down_gives_friendly_error(): void
    {
        Http::fake(fn () => throw new \Illuminate\Http\Client\ConnectionException('refused'));
        $this->post('/songs', ['file' => UploadedFile::fake()->create('a.mp3', 10)])
            ->assertSessionHasErrors(['file' => 'O serviço de análise está indisponível. Tente novamente em instantes.']);
    }

    public function test_index_lists_songs_and_syncs_status(): void
    {
        $this->song();
        Http::fake(["analyzer.test/v1/songs/".self::ID => Http::response([
            'status' => 'completed', 'stage' => null, 'error' => null, 'duration' => 268.3, 'key' => 'F major',
        ])]);

        $this->get('/')->assertInertia(fn ($page) => $page
            ->component('Songs/Index')
            ->has('songs', 1)
            ->where('songs.0.status', 'completed')
            ->where('songs.0.key_name', 'F major'));
        $this->assertDatabaseHas('songs', ['id' => self::ID, 'status' => 'completed', 'key_name' => 'F major']);
    }

    public function test_failed_status_records_error(): void
    {
        $this->song();
        Http::fake(["analyzer.test/v1/songs/".self::ID => Http::response([
            'status' => 'failed', 'error' => ['code' => 'decode_error', 'message' => 'Falha ao decodificar'],
        ])]);
        $this->getJson('/songs/'.self::ID.'/status')
            ->assertOk()->assertJsonPath('song.status', 'failed')->assertJsonPath('song.error.message', 'Falha ao decodificar');
    }

    public function test_status_survives_analyzer_outage(): void
    {
        $this->song();
        Http::fake(fn () => throw new \Illuminate\Http\Client\ConnectionException('refused'));
        $this->getJson('/songs/'.self::ID.'/status')->assertOk()->assertJsonPath('analyzer_reachable', false)->assertJsonPath('song.status', 'pending');
    }

    public function test_unknown_song_is_404(): void
    {
        $this->get('/songs/naoexiste')->assertNotFound();
        $this->get('/songs/naoexiste/audio')->assertNotFound();
    }

    public function test_data_endpoint_aggregates_results(): void
    {
        $this->song(['status' => 'completed']);
        $base = 'analyzer.test/v1/songs/'.self::ID;
        Http::fake([
            "$base/chords" => Http::response(['segments' => [['start' => 0, 'end' => 2, 'chord' => 'F']], 'edited' => null]),
            "$base/analysis" => Http::response(['run_id' => 'r1', 'key' => ['name' => 'F major']]),
            "$base/sections" => Http::response(['sections' => [['index' => 1]]]),
            "$base/report" => Http::response('relatorio', 200, ['Content-Type' => 'text/plain']),
            "$base/history" => Http::response(['runs' => []]),
        ]);
        $this->getJson('/songs/'.self::ID.'/data')->assertOk()
            ->assertJsonPath('chords.0.chord', 'F')->assertJsonPath('analysis.run_id', 'r1')->assertJsonPath('report', 'relatorio');
    }

    public function test_save_chords_validates_and_forwards(): void
    {
        $this->song(['status' => 'completed']);
        Http::fake(['analyzer.test/v1/songs/'.self::ID.'/chords/edited' => Http::response(['segments' => []])]);

        $bad = $this->putJson('/songs/'.self::ID.'/chords', ['segments' => [['start' => 0, 'end' => 2, 'chord' => '<script>']]]);
        $bad->assertStatus(422);
        $this->putJson('/songs/'.self::ID.'/chords', ['segments' => [['start' => 2, 'end' => 1, 'chord' => 'C']]])->assertStatus(422);

        $this->putJson('/songs/'.self::ID.'/chords', ['base_run_id' => 'r1', 'segments' => [['start' => 0, 'end' => 2, 'chord' => 'C/E']]])->assertOk();
        Http::assertSent(fn (Request $r) => $r->method() === 'PUT' && $r['segments'][0]['chord'] === 'C/E' && $r->hasHeader('X-Internal-Token'));
    }

    public function test_reanalyze_resets_state_and_conflict_is_reported(): void
    {
        $this->song(['status' => 'completed', 'key_name' => 'F major']);
        Http::fake(['analyzer.test/v1/songs/'.self::ID.'/reanalyze' => Http::sequence()
            ->push(['id' => self::ID, 'status' => 'pending'], 202)
            ->push(['detail' => 'Já existe uma análise em andamento.'], 409)]);

        $this->postJson('/songs/'.self::ID.'/reanalyze')->assertStatus(202)->assertJsonPath('song.status', 'pending');
        $this->postJson('/songs/'.self::ID.'/reanalyze')->assertStatus(409);
    }

    public function test_audio_is_proxied_with_range_and_never_public(): void
    {
        $this->song(['status' => 'completed']);
        Http::fake(['analyzer.test/v1/songs/'.self::ID.'/audio' => Http::response('0123456789', 206, [
            'Content-Type' => 'audio/mpeg', 'Content-Range' => 'bytes 0-9/100', 'Content-Length' => '10',
        ])]);

        $res = $this->get('/songs/'.self::ID.'/audio', ['Range' => 'bytes=0-9']);
        $res->assertStatus(206)->assertHeader('Content-Range', 'bytes 0-9/100')->assertHeader('Accept-Ranges', 'bytes');
        $this->assertSame('0123456789', $res->streamedContent());
        Http::assertSent(fn (Request $r) => $r->hasHeader('Range', 'bytes=0-9') && $r->hasHeader('X-Internal-Token', 'secret-token'));
    }
}
