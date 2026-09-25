ifndef K65_PATH
$(error K65_PATH is not set - point it to the K65 SDK root, e.g. export K65_PATH=~/Projects/Programowanie/Demoscene/tools/k65)
endif

ifeq ($(OS),Windows_NT)
	STELLABIN=${K65_PATH}\bin\Stella.exe
else
	STELLABIN=stella
endif

K65=${K65_PATH}/workdir/k65.exe
FilesList=files.lst
ROM=bin/demo.bin

# Stella >= 6 dropped -propsfile, so cartridge properties are passed directly:
# PAL timing, F4 (8 x 4K banks) bankswitching, phosphor off
STELLAFLAGS=-format PAL -bs F4 -pp NO

SOURCES=$(shell grep -oE '^[^-][^[:space:]]*\.k65' $(FilesList)) system_a2600.nut $(FilesList)

.PHONY: all run check clean

all: $(ROM)

$(ROM): $(SOURCES)
	$(K65) @$(FilesList)

run: $(ROM)
	$(STELLABIN) $(STELLAFLAGS) $(ROM)

# headless check: 300 frames, FIRE at frames 60 and 160 (rainbow -> plasma -> eqsine),
# every frame must be 312 lines; frames 30/140/290 rendered -> bin/frames.png
check: $(ROM)
	uv run --quiet --with py65 --with pillow tools/vcs_frame_check.py $(ROM) --frames 300 --press 60,160 --show 30,140,290 --png bin/frames.png

clean:
	rm -f bin/demo.bin bin/demo.gmap bin/demo.lst bin/demo.sym bin/frames.png
