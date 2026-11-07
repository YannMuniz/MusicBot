<?php

use App\Http\Controllers\SoloController;
use App\Http\Controllers\SongController;
use Illuminate\Support\Facades\Route;

Route::get('/', [SongController::class, 'index'])->name('songs.index');
Route::post('/songs', [SongController::class, 'store'])->name('songs.store');
Route::get('/songs/{song}', [SongController::class, 'show'])->name('songs.show');
Route::get('/songs/{song}/status', [SongController::class, 'status'])->name('songs.status');
Route::get('/songs/{song}/learning', [SongController::class, 'learning'])->name('songs.learning');
Route::post('/songs/{song}/review', [SongController::class, 'review'])->name('songs.review');
Route::get('/songs/{song}/data', [SongController::class, 'data'])->name('songs.data');
Route::get('/songs/{song}/audio', [SongController::class, 'audio'])->name('songs.audio');
Route::put('/songs/{song}/chords', [SongController::class, 'saveChords'])->name('songs.chords');
Route::post('/songs/{song}/reanalyze', [SongController::class, 'reanalyze'])->name('songs.reanalyze');

Route::prefix('/songs/{song}/solos')->name('solos.')->group(function () {
    Route::get('/', [SoloController::class, 'index'])->name('index');
    Route::post('/', [SoloController::class, 'store'])->name('store');
    Route::patch('/{solo}', [SoloController::class, 'update'])->where('solo', 's[0-9]+')->name('update');
    Route::delete('/{solo}', [SoloController::class, 'destroy'])->where('solo', 's[0-9]+')->name('destroy');
    Route::post('/{solo}/transcribe', [SoloController::class, 'transcribe'])->where('solo', 's[0-9]+')->name('transcribe');
    Route::get('/{solo}/tab', [SoloController::class, 'tab'])->where('solo', 's[0-9]+')->name('tab');
    Route::put('/{solo}/tab', [SoloController::class, 'saveTab'])->where('solo', 's[0-9]+')->name('tab.save');
    Route::post('/{solo}/retab', [SoloController::class, 'retab'])->where('solo', 's[0-9]+')->name('retab');
});
