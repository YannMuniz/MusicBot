<?php

namespace Tests;

use Illuminate\Foundation\Testing\TestCase as BaseTestCase;
use RuntimeException;

abstract class TestCase extends BaseTestCase
{
    /**
     * Trava de segurança: RefreshDatabase apaga tabelas, então os testes só rodam em SQLite em memória
     * (em Docker, passe -e APP_ENV=testing -e DB_CONNECTION=sqlite -e DB_DATABASE=:memory:).
     */
    public function createApplication()
    {
        $app = parent::createApplication();
        $default = $app['config']->get('database.default');
        if (! $app->environment('testing') || $default !== 'sqlite' || $app['config']->get('database.connections.sqlite.database') !== ':memory:') {
            throw new RuntimeException("Testes abortados: ambiente ou conexão '$default' inadequados (exige APP_ENV=testing e SQLite em memória); evitando apagar dados reais.");
        }

        return $app;
    }
}
