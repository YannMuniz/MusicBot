<?php

return [
    'analyzer' => [
        'url' => env('ANALYZER_URL', 'http://analyzer:8000'),
        'token' => env('ANALYZER_INTERNAL_TOKEN', ''),
        'timeout' => (int) env('ANALYZER_TIMEOUT', 30),
        'upload_timeout' => (int) env('ANALYZER_UPLOAD_TIMEOUT', 180),
    ],
    // Limite de upload validado no Laravel (o analisador valida de novo o tipo real e a duração).
    'max_upload_mb' => (int) env('HARMONIA_MAX_UPLOAD_MB', 100),
];
