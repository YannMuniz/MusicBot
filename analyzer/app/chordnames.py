"""Forma canônica dos nomes de acorde digitados pelo usuário.

A cifra brasileira escreve 7ª maior como "7M" (C#7M, Cm7M); o analisador usa "maj7"/"mM7". Sem normalizar,
"C#7M" e "C#maj7" seriam acordes diferentes para correções, memória e avaliação.
"""
import re

_RE = re.compile(r"^([A-G][#b]?)([^/]*)(?:/([A-G][#b]?))?$")
# (padrão no início do sufixo, canônico). A ordem importa: o mais específico primeiro.
_RULES = [
    (re.compile(r"^(?:m|min|-)(?:7M|M7|maj7|Maj7|\(maj7\)|\(M7\)|\(7M\)|Δ)"), "mM7"),
    (re.compile(r"^(?:7M|M7|maj7|Maj7|ma7|Δ7|Δ)(?![0-9])"), "maj7"),
    (re.compile(r"^(?:9M|M9|Maj9)"), "maj9"),
]


def canonical(label: str) -> str:
    m = _RE.match(label or "")
    if not m:
        return label
    root, suffix, bass = m.groups()
    for rx, repl in _RULES:
        mm = rx.match(suffix)
        if mm:
            suffix = repl + suffix[mm.end():]
            break
    return root + suffix + (f"/{bass}" if bass else "")
