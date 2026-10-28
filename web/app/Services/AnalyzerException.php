<?php

namespace App\Services;

use RuntimeException;

class AnalyzerException extends RuntimeException
{
    public function __construct(
        public readonly string $userMessage,
        public readonly int $httpStatus = 502,
        public readonly ?string $errorCode = null,
    ) {
        parent::__construct($userMessage);
    }
}
