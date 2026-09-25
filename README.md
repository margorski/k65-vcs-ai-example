# k65-vcs-ai-example

Przykładowy projekt na Atari 2600 (VCS) w asemblerze K65, zbudowany na wzór
`k65-templates/atarivcs-demo-template`. W tle gra muzyka z szablonu. Efekty:

1. **Tęczowe tło** – każda linia ekranu ma własny kolor (12 odcieni PAL z cieniowaniem jasności,
   tablica generowana w czasie kompilacji przez evaluator K65), przewijanie z sinusowym falowaniem.
2. **Plazma** – klasyczna plazma "suma sinusów" liczona w locie: 7 kolumn x 113 wierszy,
   kolor tła (`COLUBK`) zmieniany 7 razy w trakcie każdej linii (co 8 cykli CPU), druga linia
   każdego wiersza przesunięta o 12 px ("cegiełka" – podwaja pozorną rozdzielczość). Dwie fale
   pionowe, dwie poziome, "oddychający" zoom i cykliczna paleta 8 barw.
3. **EQ Sine** – podwójna helisa (DNA) z 32 kul zrobionych z 2 multipleksowanych sprite'ów
   (16 slotów, w każdym P0 i P1 przestawiane przez RESP/HMOVE). Kula z przodu (P0) jest większa
   i jaśniejsza – efekt 3D. Reakcja na muzykę (odtwarzacz kopiuje co ramkę AUDV/AUDF/AUDC do RAM):
   - **choreografia sekcji** (tabela z analizy utworu): spokojne części = czysta szeroka helisa
     w błękitach, główne = equalizer w tęczy, breakdowny = cienki czerwony kręgosłup pulsujący
     na stopie, build-upy = ogromna, szybko wirująca złota helisa; przejścia płynne + błysk,
   - **melodia**: wysokość nuty -> położenie garbu (chodzi góra-dół z melodią),
   - **stopa** (AUDC 15): pompowanie całej helisy, szarpnięcie obrotu, błysk; hi-haty: mały błysk,
   - **tło** w kolorze sekcji, kontrastowym do helisy (bordo / granat / ciemna zieleń / fiolet),
     delikatnie pulsujące na stopie i hi-hatach; czarna ramka z playfieldu po bokach zakrywa
     "grzebień" HMOVE.

**Sterowanie:** FIRE (joystick 0) lub SELECT – płynne wygaszenie i przejście do następnego efektu.
W Stelli: spacja = FIRE, F1 = SELECT.

## Wymagania

- zmienna `K65_PATH` wskazująca na katalog K65 SDK (np. `~/Projects/Programowanie/Demoscene/tools/k65`)
- `stella` w PATH (w Windows: `Stella.exe` w `%K65_PATH%\bin`)
- opcjonalnie `uv` – dla `make check`

## Użycie

```sh
make          # kompilacja -> bin/demo.bin
make run      # kompilacja + uruchomienie w Stelli (PAL, F4)
make check    # test bez emulatora: 300 ramek, 2x FIRE (wszystkie efekty), liczba linii + bin/frames.png
make clean
```

## Pliki

- `effects/rainbow.k65` – efekt tęczy (parametry na górze pliku: liczba linii, amplituda falowania)
- `effects/plasma.k65` – plazma (bank `bank2`, wywoływana przez `far plasma`)
- `effects/eqsine.k65` – helisa-equalizer na sprite'ach (bank `bank3`)
- `util.k65` – m.in. `FxStart`/`FxUpdate`/`FxFadeLevel`: przycisk + fade in/out
- `main.k65`, `_defs.k65`, `_gamedefs.k65`, `util.k65`, `music/` – jak w szablonie
- `docs/` – skrócona wiedza o K65 i Atari 2600 (kontekst dla AI), `CLAUDE.md` – punkt wejścia dla AI
- `tools/vcs_frame_check.py` – prosty emulator 6502 + TIA (tło, sprite'y) mierzący timing i renderujący klatki
- `tools/song_analysis.py` – odtwarza cały utwór bez GUI i wypisuje cechy każdej sekcji (głośność, ataki, barwy)

Różnice względem szablonu: `make` tylko buduje (nie uruchamia), Stella dostaje parametry z linii
komend (Stella 6.x nie ma już `-propsfile`), doszły `make check` i `make clean`.
