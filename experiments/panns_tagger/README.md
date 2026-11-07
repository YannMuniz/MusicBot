# PANNs Cnn14 como etiquetador de voz/instrumento — NÃO VALIDADO, fora do pipeline

Escrito e depois retirado do analisador porque os pesos (Cnn14_mAP=0.431.pth, 327 MB, Zenodo 3987831) **não puderam ser
baixados** no ambiente de desenvolvimento (4–12 KB/s), então o código nunca rodou com pesos reais e não foi avaliado.
- Licenças: código MIT; pesos CC BY 4.0 (atribuição obrigatória); rótulos AudioSet CC BY 4.0. md5 do checkpoint (Zenodo): 541141fa2ee191a88f24a3219fff024e.
- Classes úteis (índices AudioSet): Singing 27, Male singing 32, Female singing 33, Guitar 140, Electric guitar 141, Bass guitar 142,
  Keyboard 152, Piano 153, Drum kit 162, Music 137.
- Para adotar: baixar os pesos, fixar o SHA-256, validar o mapeamento de chaves do checkpoint (`logmel_extractor.melW` → `mel_w`),
  medir voz-vs-instrumental e instrumento nas cifras alinhadas (eval/) e só então ligar ao pipeline. Custo esperado em CPU: ~0,1 s por janela de 6 s.
