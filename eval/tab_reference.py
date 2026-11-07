"""Parser de tablatura ASCII (formato Cifra Club) -> sequência de notas de referência (por ORDEM, sem tempos).

Cada linha de corda é varrida por colunas; números = casas; entre números, / (slide acima), \\ (slide abaixo), h (hammer-on),
p (pull-off), ~ (vibrato). Cada número gera uma nota (6/8 = nota 6 e nota 8). Afinação padrão assumida (altura real).
Limites: tablaturas da internet são transcrições de usuários (podem divergir da gravação e não trazem ritmo); só a ORDEM e as
alturas são usadas. Uso: python tab_reference.py tab.txt saida.json
"""
import json
import re
import sys

OPEN = {"e": 64, "B": 59, "G": 55, "D": 50, "A": 45, "E": 40}      # cordas 1..6 por letra (a 1ª 'E' do texto é a aguda)
ORDER = [64, 59, 55, 50, 45, 40]


def parse_part(lines: list, part: int) -> list:
    strings = [l for l in lines if re.match(r"^[EBGDAe]\|", l)][:6]
    notes = []
    for si, line in enumerate(strings):
        body = line.split("|", 1)[1]
        for m in re.finditer(r"\d+", body):
            col = m.start()
            fret = int(m.group())
            before = body[col - 1] if col > 0 else "-"
            after = body[m.end()] if m.end() < len(body) else "-"
            tech = {"/": "slide_up_in", "\\": "slide_down_in", "h": "hammer", "p": "pull"}.get(before)
            if after == "~":
                tech = (tech or "") + "+vibrato"
            notes.append({"part": part, "col": col, "string": si + 1, "fret": fret, "pitch": ORDER[si] + fret, "technique": tech})
    return sorted(notes, key=lambda n: (n["part"], n["col"], n["string"]))


def parse_tab(text: str) -> list:
    blocks = re.split(r"Parte\s+\d+\s+de\s+\d+", text)[1:]
    out = []
    for i, b in enumerate(blocks, start=1):
        out += parse_part(b.splitlines(), i)
    return out


if __name__ == "__main__":
    notes = parse_tab(open(sys.argv[1], encoding="utf-8").read())
    json.dump({"source": "Cifra Club - O Tempo - Oficina G3 (tablatura do solo, 4 partes)", "tuning": "standard (E A D G B E), altura real",
               "caveats": "transcrição de usuário; sem ritmo; pode divergir da gravação", "notes": notes}, open(sys.argv[2], "w"), indent=1)
    print(len(notes), "notas")
