<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class Song extends Model
{
    public $incrementing = false;

    protected $keyType = 'string';

    protected $guarded = [];

    public function isFinal(): bool
    {
        return in_array($this->status, ['completed', 'failed'], true);
    }

    /** Atualiza o índice local a partir do resumo devolvido pelo analisador. */
    public function applySummary(array $s): void
    {
        $this->fill([
            'status' => $s['status'] ?? $this->status,
            'stage' => $s['stage'] ?? null,
            'error_code' => $s['error']['code'] ?? null,
            'error_message' => $s['error']['message'] ?? null,
            'duration' => $s['duration'] ?? $this->duration,
            'key_name' => $s['key'] ?? $this->key_name,
        ])->save();
    }

    public function toFrontend(): array
    {
        return [
            'id' => $this->id,
            'title' => $this->title,
            'original_filename' => $this->original_filename,
            'status' => $this->status,
            'stage' => $this->stage,
            'error' => $this->error_message ? ['code' => $this->error_code, 'message' => $this->error_message] : null,
            'duration' => $this->duration,
            'key_name' => $this->key_name,
            'created_at' => $this->created_at?->toIso8601String(),
        ];
    }
}
