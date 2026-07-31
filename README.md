# Calorie Tracker for Home Assistant

A HACS custom integration that calculates your **Total Daily Energy Expenditure
(TDEE)** in real time using evidence-based metabolic equations, exercise data
from connected devices (Peloton) or manual entry, and dynamic weight / body
composition data from smart scales.

```
TDEE = RMR + TEF + Net Exercise EE + NEAT
```

In practice the integration computes:

```
base_daily_kcal  = RMR × PAL_factor          (PAL covers NEAT + TEF + untracked movement)
total_daily_kcal = base_daily_kcal + Σ net_exercise_kcal
```

## Features

- **Three selectable RMR equations** — Mifflin-St Jeor (default, most validated),
  Harris-Benedict, and Cunningham (fat-free-mass based, unlocked automatically
  when body composition data is available).
- **Smart scale support** — map any Home Assistant weight / body-fat / muscle /
  bone / water / BMI sensor (Withings, Xiaomi, Garmin, Fitbit, Renpho, Eufy, or
  any generic scale). Automatic lbs/stones→kg conversion, optional 7-day
  rolling-average smoothing, and stale-data alerts. The body fat entity accepts
  either a **percentage** sensor or a **fat mass** sensor (kg/lb) — many scales
  such as Withings report fat mass, and the unit is detected automatically.
- **kg or lb display** — pick your preferred weight unit during setup (or in
  options). Values are stored in kg internally so statistics stay consistent,
  and Home Assistant renders all weight sensors in pounds when selected.
- **Peloton integration** — converts device-reported *gross* calories to *net*
  calories by subtracting the resting metabolic component for the session
  duration, with a configurable correction factor (consumer devices can
  overestimate burn by 15–30%).
- **MET-based manual logging** — `calorie_tracker.log_exercise` with a built-in
  MET table (2011 Compendium of Physical Activities) using **net METs**
  (MET − 1) so RMR is never double-counted.
- **Goals & macros** — daily calorie budget (TDEE − 500 for weight loss, +300
  for muscle gain) and protein target (weight × multiplier, default 1.8 g/kg).
- **Adaptive budget mode** — base the daily budget on today's TDEE (default),
  or on a rolling 7-day / 30-day average TDEE built from your actual logged
  exercise. The rolling modes spread workout calories evenly across the week,
  giving a steady daily target instead of one that spikes on workout days.
- **Event-driven, no polling** — recalculates instantly via
  `async_track_state_change_event` when a mapped entity updates.
- **Daily reset at local midnight** — exercise totals reset; weight and body
  composition persist. Sensors declare proper `state_class` values so Home
  Assistant long-term statistics work natively.

## Installation

### HACS (recommended)

1. HACS → Integrations → ⋮ → *Custom repositories* → add this repository as
   type **Integration**.
2. Install **Calorie Tracker** and restart Home Assistant.
3. Settings → Devices & Services → *Add Integration* → **Calorie Tracker**.

### Manual

Copy `custom_components/calorie_tracker/` into your Home Assistant
`config/custom_components/` directory and restart.

## Sensors

| Entity | Description | Unit |
|---|---|---|
| `sensor.calorie_tracker_rmr` | Resting Metabolic Rate | kcal/d |
| `sensor.calorie_tracker_base_daily` | RMR × PAL (non-exercise expenditure) | kcal/d |
| `sensor.calorie_tracker_exercise_gross` | Today's gross exercise calories | kcal |
| `sensor.calorie_tracker_exercise_net` | Today's net exercise calories | kcal |
| `sensor.calorie_tracker_tdee` | Total Daily Energy Expenditure | kcal |
| `sensor.calorie_tracker_tdee_7d_avg` | Base + average daily net exercise over the last 7 days | kcal |
| `sensor.calorie_tracker_tdee_30d_avg` | Base + average daily net exercise over the last 30 days | kcal |
| `sensor.calorie_tracker_exercise_count` | Exercise sessions today | — |
| `sensor.calorie_tracker_correction_factor` | Active correction factor | — |
| `sensor.calorie_tracker_daily_budget` | TDEE ± goal offset | kcal |
| `sensor.calorie_tracker_protein_target` | weight × protein multiplier | g |
| `sensor.calorie_tracker_weight` | Current weight (smoothed if enabled) | kg |
| `sensor.calorie_tracker_body_fat` | Body fat percentage | % |
| `sensor.calorie_tracker_fat_free_mass` | weight × (1 − BF/100) | kg |
| `sensor.calorie_tracker_muscle_mass` | Muscle mass from scale | kg |
| `sensor.calorie_tracker_bmi` | BMI (from scale or calculated) | kg/m² |
| `sensor.calorie_tracker_weight_trend` | 7-day rolling average weight | kg |
| `sensor.calorie_tracker_workout_recommendation` | Today's recommended workout (deterministic engine) | text |
| `sensor.calorie_tracker_acwr` | EWMA Acute:Chronic Workload Ratio (`initializing` < 14 days of data) | ratio |
| `sensor.calorie_tracker_weekly_aerobic_minutes` | Rolling 7-day aerobic minutes vs. ACSM target | min |
| `sensor.calorie_tracker_monthly_distance_progress` | Calendar-month distance vs. goal | mi/km |

The TDEE sensor exposes attributes with the active equation, PAL factor,
today's session list (type, duration, gross/net kcal, source, HR-monitor
flag), correction factor, weight source, and last-update timestamp.

## Services

| Service | Parameters | Description |
|---|---|---|
| `calorie_tracker.log_exercise` | `activity_type`, `duration_minutes`, `calories` (optional) | Log a session. Without `calories`, uses the MET table; with `calories`, treats it as gross device calories and subtracts the resting component. |
| `calorie_tracker.set_correction_factor` | `factor` (0.50–1.00) | Update the exercise correction factor. |
| `calorie_tracker.log_weight` | `weight`, `unit` (optional: `kg`/`lb`, defaults to the configured display unit) | Manually log a weight measurement. |
| `calorie_tracker.log_body_fat` | `body_fat_pct` | Manually log body fat (1–60%). |
| `calorie_tracker.reset_daily` | — | Manually reset today's exercise totals. |

Example:

```yaml
service: calorie_tracker.log_exercise
data:
  activity_type: cycling_moderate_12mph
  duration_minutes: 45
```

## How the math works

**RMR** (kcal/day), selectable:

- *Mifflin-St Jeor (default)*: `10w + 6.25h − 5a + 5` (male) / `− 161` (female)
- *Harris-Benedict*: `13.7516w + 5.0033h − 6.7550a + 66.4730` (male) /
  `9.5634w + 1.8496h − 4.6756a + 655.0955` (female)
- *Cunningham*: `22 × FFM + 500`, where `FFM = w × (1 − BF%/100)`

**Device exercise (Peloton)** — gross → net:

```
corrected_gross = reported_kcal × correction_factor
resting         = (RMR / 1440) × duration_minutes
net             = max(0, corrected_gross − resting)
```

**Manual exercise (MET)** — net METs avoid double-counting RMR:

```
net = max(0, (MET − 1) × weight_kg × duration_minutes / 60)
```

**Daily totals**:

```
base   = RMR × PAL          (sedentary 1.2 … very active 1.725)
TDEE   = base + Σ net exercise
budget = TDEE + goal_offset (−500 / 0 / +300)
```

**Rolling averages** — each day's final totals are archived at midnight, and:

```
TDEE_7d_avg  = base + mean(daily net exercise, last 7 days incl. today)
TDEE_30d_avg = base + mean(daily net exercise, last 30 days incl. today)
```

Only days recorded since installation count toward the average, so a fresh
install is not dragged toward zero. The *budget mode* setting picks which
TDEE (today / 7-day / 30-day) the daily budget is derived from.

Note: the PAL preset remains the estimate for non-exercise activity (NEAT).
Truly calibrating NEAT from data would require food-intake and weight-change
tracking, which this integration does not collect.

## Workout recommendation engine

A deterministic (no LLM/AI APIs) load-management engine analyzes your training
history and produces a daily recommendation:

- **EWMA ACWR** — acute (7-day, λ=0.25) and chronic (28-day, λ≈0.069)
  exponentially weighted moving averages of daily net exercise calories.
  `ACWR = acute / chronic`. Below 0.8 is underloading, 0.8–1.5 acceptable,
  1.5–2.0 triggers active recovery, above 2.0 triggers full passive rest.
  With fewer than 14 days of history the ratio reports `initializing` and the
  engine falls back to a 75th-percentile absolute-load trigger.
- **Recovery spacing** — consecutive training days are capped at
  `7 − weekly_rest_days_target`; strength days are never recommended
  back-to-back (ACSM 48–72 h guidance); fewer than 2 mobility/yoga sessions in
  7 days appends a stretch nudge.
- **Polarized distribution** — sessions tagged HIIT/interval/tabata (or with
  average HR > 80% of 220 − age) count as high intensity; when they exceed the
  configurable threshold (default 25%) of cardio sessions over 14 days, the
  engine prescribes Zone 2 volume.
- **Goal pacing** — monthly cycling distance and strength-session goals drive
  the balanced-day suggestion, with the required daily pace exposed as a
  sensor attribute.

Decision priority: passive rest → active recovery → strength balance →
polarization → goal pacing. Every derived flag (`mandatory_rest`,
`strength_lockout`, `acute_fatigue`, …) is exposed as an attribute on
`sensor.calorie_tracker_workout_recommendation` for use in automations.

Sessions are auto-classified from their activity name (strength / mobility /
cycling / cardio). Map the Peloton distance entity (and log `distance` in
`log_exercise`) to feed the monthly distance goal.

## Nutrition intake & energy balance (SparkyFitness)

Food intake is sourced exclusively from a self-hosted
[SparkyFitness](https://github.com/CodeWithCJ/SparkyFitness) instance — no
third-party food-database APIs. SparkyFitness resolves foods to nutrients at
logging time; this integration performs **no** independent nutrient lookup,
barcode scanning, or imputation (missing macros stay unknown, never zero).

- **Polling** — the food diary is fetched on a configurable interval (default
  15 min) with exponential backoff on failure. Intake sensors go *unavailable*
  (not zero) if the source is down with no cached data; the last successful
  day is cached so a restart during an outage does not wipe the day. Each poll
  replaces the whole day, so mid-day edits and deletions upstream are honored.
- **Write-back** — completed Peloton/manual workouts are pushed to
  SparkyFitness with a stable external id, so reloads cannot create
  duplicates. Toggleable in config.
- **Manual fallback** — `calorie_tracker.log_food` records intake when the
  instance is offline; manual entries are merged and counted separately
  (`manual_entry_count`).
- **TEF** — macronutrient-specific by default
  (`protein·4·0.25 + carbs·4·0.075 + fat·9·0.02`), falling back to a flat 10%
  (flagged `tef_estimated`) when macros cover <80% of the day's calories. The
  PAL multiplier's assumed TEF share is subtracted before the explicit TEF is
  added, so TEF is never double-counted in TDEE.
- **Energy balance** — `intake − TDEE`, classified after a configurable
  end-of-day cutoff (default 20:00) into surplus / minimal / guideline (250–750)
  / aggressive (751–1000) / very aggressive (>1000). Incomplete logging
  (source stale >6 h, missing macros, or <500 kcal after cutoff) yields
  `insufficient_data` instead of a spurious deficit.
- **Protein adequacy** — target from total body weight (default 1.4 g/kg),
  fat-free mass (1.5 g/kg FFM), or absolute grams; bands at <80% / 80–99% /
  100–120% / >120%, with a critical flag under 0.5 g/kg and an advisory when
  the 7-day rolling intake is ≥2.0 g/kg.
- **Recommendation integration** — a sustained 7-day deficit beyond
  1000 kcal/day or ≥3 below-floor days in a week inserts an "Underfueling
  Detected — Light Activity Only" tier into the workout engine (below
  rest/ACWR, above strength/polarization). The engine reports status against
  *your* targets only and never prescribes an intake.
- **Dynamic RMR** — an optional clinical metabolic-device sensor overrides all
  static RMR equations while its reading is <24 h old, with automatic
  fallback and a logged warning when stale.

> **Note on API paths:** SparkyFitness endpoint paths and payload mapping are
> centralized in `const.py` / `sparkyfitness.py::normalize_entry`. If your
> instance version uses a different layout, those are the only places to edit.

## Smart scale behavior

- Weight updates trigger an immediate recalculation of RMR and all downstream
  values; lbs and stones are converted automatically from the entity's
  `unit_of_measurement`.
- If the scale entity goes `unavailable`/`unknown`, the last valid value is
  retained (`weight_source: last_known`).
- If no reading arrives within the stale threshold (default 7 days), the
  weight sensor sets `weight_data_stale: true` and a persistent notification
  is created. The last known weight continues to be used.
- The mapped body fat entity may report a percentage (`%`) **or** a fat mass
  (kg/lb): fat mass is converted with `body_fat_pct = fat_mass / weight × 100`
  and re-derived whenever a new weight arrives.
- Body fat readings outside 1–60% are rejected as glitches.
- Optional 7-day rolling-average smoothing reduces day-to-day hydration noise;
  the raw reading is kept as a `raw_weight` attribute.

## Important scientific notes

- All predictive RMR equations have **±10–25% individual-level variability**
  compared to indirect calorimetry. These are estimates, not measurements.
- The Mifflin-St Jeor equation is validated for adults aged 18–65. For older
  adults, Harris-Benedict may have slightly better individual-level precision.
- MET values represent population averages and do not account for individual
  fitness level, environmental conditions, or movement efficiency.
- The correction factor for device-reported calories is user-configurable
  because device accuracy varies by device model, exercise type, and
  individual physiology.
- Smart scale body composition measurements use bioelectrical impedance
  analysis (BIA), which varies with hydration status, recent meals, and time
  of day. For best consistency, weigh at the same time daily (morning, fasted,
  after voiding).
- **This integration is for personal wellness tracking only and is not a
  medical device. It does not provide medical or nutritional advice.**
  Caloric restriction below 1200 kcal/day (women) or 1500 kcal/day (men)
  should be undertaken only under medical supervision.
- Protein guidance differs between professional societies. A joint advisory
  from the American College of Lifestyle Medicine, American Society for
  Nutrition, Obesity Medicine Association, and The Obesity Society recommends
  protein intake not fall below 0.4–0.5 g/kg/day and that prolonged intake at
  or above 2 g/kg/day be avoided. The American Association of Clinical
  Endocrinology states that intake >2 g/kg/day may not have adverse health
  effects, with a tolerable upper limit around 3.5 g/kg/day. Users with
  chronic kidney disease, liver disease, or who are pregnant should consult a
  clinician before setting targets.
- Protein targets based on total body weight can substantially overestimate
  requirements in individuals with obesity. The fat-free mass basis
  (1.5 g/kg FFM/day) may be more accurate but depends on bioelectrical
  impedance data, which varies with hydration status and time of day.
- All nutrition data quality is inherited from SparkyFitness. Accuracy depends
  entirely on the food database entries and portion sizes recorded upstream.
  Self-reported dietary intake is systematically underreported, and app-based
  nutrient calculations have been shown to run lower than research-grade
  dietary analysis software — protein in particular. Logged values should be
  treated as a lower bound.
- Energy expenditure falls disproportionately during weight loss (adaptive
  thermogenesis). Predicted weight loss based on a fixed calories-per-pound
  conversion overestimates actual results over time; this integration never
  projects weight loss from a static 3500 kcal/lb rule, and the optional
  adaptive-thermogenesis correction is a first-order approximation that is
  not individually validated.
- All targets are user-configured. The integration reports status against the
  user's own settings and does not prescribe intake.

## Development

The metabolic math lives in `calculator.py` with no Home Assistant
dependencies. Run the unit tests with:

```
python -m pytest tests/ -v
```

## License

[MIT](LICENSE)
