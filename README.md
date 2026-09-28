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
     błyskające od czerni na stopie i hi-hatach; czarna ramka z playfieldu po bokach zakrywa
     "grzebień" HMOVE,
   - **skaner** – pozioma linia z playfieldu (kule przelatują przed nią) zjeżdżająca w dół w takt
     utworu: w spokojnych sekcjach i breakdownach 1 przebieg na 2 wzory, w głównych 1 na wzór,
     w build-upach 2 na wzór; na stopie podskakuje w górę, hi-haty i stopy ją rozjaśniają,
   - **budowanie napięcia**: przez intro (sekwencje 0–7, ~14 s) skaner z piłką stoją u góry
     (piłka tylko podskakuje na hi-hatach), ruszają, gdy wchodzi bas (`EQ_SCAN_START` w eqsine.k65),
   - **piłeczka (ball)** – "karaoke": jedzie po skanerze w lewo i prawo raz na wzór i podskakuje
     po paraboli na stopie (wysokość zależna od sekcji) oraz lekko na hi-hatach; chowa się za
     kulami; podczas błysku tła jest czarną sylwetką (żeby krawędzie ekranu zostały czyste),
   - **iskry (missile M0/M1)** – na stopie z osi helisy wylatuje w obie strony chmura iskier
     w kolorach kul, rozchodząca się w poszarpane zygzaki (32 iskry z 2 missile'i).

4. **Kula 3D z "latających pikseli"** – 30 punktów na sferze obracające się jednocześnie wokół
   osi X, Y i Z, rysowane wszystkimi pięcioma obiektami TIA (P0, P1, M0, M1, ball) jako kropki 2×2.
   Obrót jest wyliczony z góry (`tools/gen_shapes.py`); w czasie
   rzeczywistym VCS wybiera klatkę, skaluje ją i rozkłada punkty na obiekty (15 pasów po 11 linii,
   w każdym 5 kropek). Punkty z tyłu kuli są ciemniejsze (rysują je P1/M1 w przyciemnionym kolorze,
   przód – P0/M0/ball w jasnym), co podkreśla trójwymiarowość. Stopa – zryw prędkości obrotu,
   hi-hat – kula pulsuje (do 120%).
   Kształt, kolor i prędkość zależą od nastroju sekcji utworu: spokojne części – niebieski
   sześcian (wolno), główne – zielona piramida, breakdowny – czerwony diament, build-upy –
   fioletowa kula (najszybciej). Zmiana kształtu: implozja (wejście w spokojną sekcję) albo
   eksplozja (wejście w energiczną). Bryły trzymają w ROM tylko obrócone wierzchołki; punkty
   na krawędziach VCS liczy sam jako średnie wierzchołków.
   Od drugiego wejścia w spokojną sekcję (sekwencja 44, ~1:17) do końca utworu kręci się
   czerwone logo Atari (Fuji, 28 punktów; obrót wokół pionu liczony na bieżąco: x = x₀·cos,
   mnożenie przez tablicę kwadratów). Po zapętleniu utworu wszystko zaczyna się od nowa.

**Obecnie włączone są efekty 4 i 3 (najpierw kula/bryły, potem EQ Sine)** – tęcza i plazma są zakomentowane w `main.k65`
(kod zostaje; żeby je włączyć, wystarczy odkomentować linie).

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
- `effects/shapes/` – efekt `shapes`: bryły 3D z punktów (bank `bank4` + `bank5`, `bank2`, `bank1`);
  każda bryła ma własny plik (`sphere.k65`, `cube.k65`, `pyramid.k65`, `diamond.k65`, `logo.k65`), wspólny kod
  to `shape_*.k65`; dane (`*_data.k65`) generuje `python3 tools/gen_shapes.py`
- `util.k65` – m.in. `FxStart`/`FxUpdate`/`FxFadeLevel`: przycisk + fade in/out
- `main.k65`, `_defs.k65`, `_gamedefs.k65`, `util.k65`, `music/` – jak w szablonie
- `docs/` – skrócona wiedza o K65 i Atari 2600 (kontekst dla AI), `CLAUDE.md` – punkt wejścia dla AI
- `tools/vcs_frame_check.py` – prosty emulator 6502 + TIA (tło, playfield, sprite'y, missile) mierzący timing i renderujący klatki
- `tools/song_analysis.py` – odtwarza cały utwór bez GUI i wypisuje cechy każdej sekcji (głośność, ataki, barwy)

Różnice względem szablonu: `make` tylko buduje (nie uruchamia), Stella dostaje parametry z linii
komend (Stella 6.x nie ma już `-propsfile`), doszły `make check` i `make clean`.
