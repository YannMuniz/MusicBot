<?php

use App\Http\Controllers\SongController;
use Illuminate\Support\Facades\Route;

Route::get('/', [SongController::class, 'index'])->name('songs.index');
Route::post('/songs', [SongController::class, 'store'])->name('songs.store');
Route::get('/songs/{song}', [SongController::class, 'show'])->name('songs.show');
Route::get('/songs/{song}/status', [SongController::class, 'status'])->name('songs.status');
Route::get('/songs/{song}/data', [SongController::class, 'data'])->name('songs.data');
Route::get('/songs/{song}/audio', [SongController::class, 'audio'])->name('songs.audio');
Route::put('/songs/{song}/chords', [SongController::class, 'saveChords'])->name('songs.chords');
Route::post('/songs/{song}/reanalyze', [SongController::class, 'reanalyze'])->name('songs.reanalyze');
