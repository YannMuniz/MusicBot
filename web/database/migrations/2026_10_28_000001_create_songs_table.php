<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    /**
     * Índice local das músicas. Os resultados da análise ficam no serviço Python
     * (storage/songs/{id}); aqui só há o necessário para listar e acompanhar o estado.
     */
    public function up(): void
    {
        Schema::create('songs', function (Blueprint $table) {
            $table->string('id', 32)->primary(); // mesmo ID do analisador
            $table->string('title');
            $table->string('original_filename');
            $table->string('status', 20)->default('pending')->index();
            $table->string('stage', 40)->nullable();
            $table->string('error_code', 60)->nullable();
            $table->text('error_message')->nullable();
            $table->float('duration')->nullable();
            $table->string('key_name', 40)->nullable();
            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('songs');
    }
};
