# k65-vcs-ai-example

Przykładowy projekt na Atari 2600 (VCS) w asemblerze K65, zbudowany na wzór
`k65-templates/atarivcs-demo-template`. Efekt: **tęczowe tło** – każda linia ekranu ma własny kolor
z 256-bajtowej tablicy (12 odcieni PAL z cieniowaniem jasności, generowanej w czasie kompilacji
przez evaluator K65), tęcza przewija się w górę z sinusowym "falowaniem". W tle gra muzyka z szablonu.

## Wymagania

- zmienna `K65_PATH` wskazująca na katalog K65 SDK (np. `~/Projects/Programowanie/Demoscene/tools/k65`)
- `stella` w PATH (w Windows: `Stella.exe` w `%K65_PATH%\bin`)
- opcjonalnie `uv` – dla `make check`

## Użycie

```sh
make          # kompilacja -> bin/demo.bin
make run      # kompilacja + uruchomienie w Stelli (PAL, F4)
make check    # test bez emulatora: liczba linii w ramce + bin/frames.png z kolorami tła
make clean
```

## Pliki

- `effects/rainbow.k65` – efekt tęczy (parametry na górze pliku: liczba linii, amplituda falowania)
- `main.k65`, `_defs.k65`, `_gamedefs.k65`, `util.k65`, `music/` – jak w szablonie
- `docs/` – skrócona wiedza o K65 i Atari 2600 (kontekst dla AI), `CLAUDE.md` – punkt wejścia dla AI
- `tools/vcs_frame_check.py` – prosty emulator 6502 (py65) mierzący timing ramki

Różnice względem szablonu: `make` tylko buduje (nie uruchamia), Stella dostaje parametry z linii
komend (Stella 6.x nie ma już `-propsfile`), doszły `make check` i `make clean`.
