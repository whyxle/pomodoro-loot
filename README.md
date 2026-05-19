# Pomodoro Loot

A Python + pywebview desktop app for gamified focus sessions.

Start an honest pomodoro timer, finish a study session, and receive loot afterward. Items, rarities, collections, and drop visuals are configured locally, so the app is not tied to a single setting.

## Core Mechanics

- Loot is granted only after a focus session is completed.
- XP is based on focused minutes.
- Each session has a difficulty contract from Warmup to Diamond, adding explicit bonus rolls and luck for harder tasks.
- Focus chains continue when the next session starts within the configurable break window, giving cumulative bonus rolls and luck.
- Anti-farm rules cap daily chain bonus rolls, reduce rewards from repeated short sessions, and add extra rolls for long focus blocks.
- Daily goals for 1 session, 60 minutes, and 120 minutes grant bonus rewards once per day.
- Every 4th completed session suggests a long break and adds an extra reward roll.
- Reset timers show when daily goals and the current focus chain expire.
- A GitHub-style activity calendar adapts color intensity to your all-time daily focus peak.
- The item collection is stored separately from the inventory.
- Presets export only the item catalog, rarities, and drop settings, without user progress.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python app.py
```

## Data And Presets

Current user JSON files (`case_*.json`) are treated as local data and ignored by git. The Path of Exile item set is saved as a local preset:

```text
local_presets/path_of_exile.json
```

Import it from the `Presets` tab if you want to keep the PoE theme in your local game.

## Architecture

- `simcase/domain/` - models, defaults, normalization, and pure calculations.
- `simcase/application/` - app use cases and the pomodoro reward loop.
- `simcase/infrastructure/` - file-based JSON storage.
- `simcase/presentation/` - pywebview API and app window.
- `simcase/web/` - HTML, CSS, and JavaScript UI.
- `tests/` - regression tests.
