"""Constants for the Calorie Tracker integration."""
from __future__ import annotations

DOMAIN = "calorie_tracker"

# Config keys — user profile
CONF_WEIGHT_KG = "weight_kg"
CONF_HEIGHT_CM = "height_cm"
CONF_DATE_OF_BIRTH = "date_of_birth"
CONF_SEX = "sex"
CONF_BODY_FAT_PCT = "body_fat_percentage"

# Config keys — metabolic
CONF_RMR_EQUATION = "rmr_equation"
CONF_ACTIVITY_LEVEL = "baseline_activity_level"
CONF_TEF_PERCENTAGE = "tef_percentage"

# Config keys — smart scale
CONF_SCALE_ENABLED = "smart_scale_enabled"
CONF_WEIGHT_ENTITY = "weight_entity"
CONF_BODY_FAT_ENTITY = "body_fat_entity"
CONF_MUSCLE_MASS_ENTITY = "muscle_mass_entity"
CONF_BONE_MASS_ENTITY = "bone_mass_entity"
CONF_WATER_PCT_ENTITY = "water_pct_entity"
CONF_BMI_ENTITY = "bmi_entity"
CONF_WEIGHT_SMOOTHING = "weight_smoothing"
CONF_STALE_THRESHOLD_DAYS = "scale_stale_threshold_days"

# Config keys — display
CONF_DISPLAY_UNIT = "display_unit"
DISPLAY_UNIT_KG = "kg"
DISPLAY_UNIT_LB = "lb"
DEFAULT_DISPLAY_UNIT = DISPLAY_UNIT_KG

# Config keys — goals
CONF_GOAL = "goal"
CONF_PROTEIN_MULTIPLIER = "protein_multiplier"
CONF_BUDGET_MODE = "budget_mode"

# Budget modes: which TDEE the daily budget is derived from.
BUDGET_MODE_TODAY = "today"
BUDGET_MODE_7D = "rolling_7d"
BUDGET_MODE_30D = "rolling_30d"
BUDGET_MODES = [BUDGET_MODE_TODAY, BUDGET_MODE_7D, BUDGET_MODE_30D]
DEFAULT_BUDGET_MODE = BUDGET_MODE_TODAY

# Days of per-day history retained for rolling averages.
HISTORY_RETENTION_DAYS = 60

# Config keys — workout recommendation engine
CONF_MONTHLY_CYCLING_DISTANCE_GOAL = "monthly_cycling_distance_goal"
CONF_WEEKLY_AEROBIC_MINUTES_GOAL = "weekly_aerobic_minutes_goal"
CONF_MONTHLY_STRENGTH_GOAL = "monthly_strength_goal"
CONF_WEEKLY_REST_DAYS_TARGET = "weekly_rest_days_target"
CONF_POLARIZATION_THRESHOLD_PCT = "polarization_threshold_pct"
CONF_PELOTON_DISTANCE_ENTITY = "peloton_distance_entity"

DEFAULT_MONTHLY_CYCLING_DISTANCE_GOAL = 100.0
DEFAULT_WEEKLY_AEROBIC_MINUTES_GOAL = 150
DEFAULT_MONTHLY_STRENGTH_GOAL = 12
DEFAULT_WEEKLY_REST_DAYS_TARGET = 1
DEFAULT_POLARIZATION_THRESHOLD_PCT = 25

# Config keys — exercise sources
CONF_PELOTON_ENABLED = "peloton_enabled"
CONF_PELOTON_WORKOUT_ENTITY = "peloton_workout_entity"
CONF_PELOTON_CALORIES_ENTITY = "peloton_calories_entity"
CONF_PELOTON_DURATION_ENTITY = "peloton_duration_entity"
CONF_PELOTON_HR_ENTITY = "peloton_heart_rate_entity"
CONF_CORRECTION_FACTOR = "exercise_correction_factor"

# Enum values
SEX_MALE = "male"
SEX_FEMALE = "female"

EQUATION_MIFFLIN = "mifflin_st_jeor"
EQUATION_HARRIS = "harris_benedict"
EQUATION_CUNNINGHAM = "cunningham"
RMR_EQUATIONS = [EQUATION_MIFFLIN, EQUATION_HARRIS, EQUATION_CUNNINGHAM]

SMOOTHING_NONE = "none"
SMOOTHING_ROLLING = "rolling_average"

GOAL_WEIGHT_LOSS = "weight_loss"
GOAL_MAINTENANCE = "maintenance"
GOAL_MUSCLE_GAIN = "muscle_gain"

GOAL_OFFSETS: dict[str, int] = {
    GOAL_WEIGHT_LOSS: -500,
    GOAL_MAINTENANCE: 0,
    GOAL_MUSCLE_GAIN: 300,
}

# Reduced PAL factors representing only the non-exercise portion of daily
# activity (NEAT + TEF + untracked movement); tracked exercise is added on top.
ACTIVITY_LEVELS: dict[str, float] = {
    "sedentary": 1.2,
    "lightly_active": 1.375,
    "moderately_active": 1.55,
    "very_active": 1.725,
}

# Defaults
DEFAULT_RMR_EQUATION = EQUATION_MIFFLIN
DEFAULT_ACTIVITY_LEVEL = "sedentary"
DEFAULT_CORRECTION_FACTOR = 1.0
DEFAULT_PROTEIN_MULTIPLIER = 1.8
DEFAULT_GOAL = GOAL_MAINTENANCE
DEFAULT_TEF_PERCENTAGE = 10
DEFAULT_STALE_THRESHOLD_DAYS = 7
DEFAULT_SMOOTHING = SMOOTHING_NONE

CORRECTION_FACTOR_MIN = 0.50
CORRECTION_FACTOR_MAX = 1.00

BODY_FAT_MIN = 1.0
BODY_FAT_MAX = 60.0

SMOOTHING_WINDOW_DAYS = 7

# Weight sources
SOURCE_SMART_SCALE = "smart_scale"
SOURCE_MANUAL = "manual"
SOURCE_LAST_KNOWN = "last_known"

# Exercise sources
EXERCISE_SOURCE_PELOTON = "peloton"
EXERCISE_SOURCE_MANUAL = "manual"

# Services
SERVICE_LOG_EXERCISE = "log_exercise"
SERVICE_SET_CORRECTION_FACTOR = "set_correction_factor"
SERVICE_LOG_WEIGHT = "log_weight"
SERVICE_LOG_BODY_FAT = "log_body_fat"
SERVICE_RESET_DAILY = "reset_daily"

ATTR_ACTIVITY_TYPE = "activity_type"
ATTR_DURATION_MINUTES = "duration_minutes"
ATTR_CALORIES = "calories"
ATTR_DISTANCE = "distance"
ATTR_FACTOR = "factor"
ATTR_WEIGHT = "weight"
ATTR_WEIGHT_UNIT = "unit"
ATTR_BODY_FAT_PCT = "body_fat_pct"

# Dispatcher signal (formatted with entry_id)
SIGNAL_UPDATE = f"{DOMAIN}_update_{{}}"

# ---------------------------------------------------------------------------
# Nutrition intake & energy balance engine
# ---------------------------------------------------------------------------

# SparkyFitness connection
CONF_SPARKY_ENABLED = "sparkyfitness_enabled"
CONF_SPARKY_BASE_URL = "sparkyfitness_base_url"
CONF_SPARKY_API_KEY = "sparkyfitness_api_key"
CONF_SPARKY_USER_ID = "sparkyfitness_user_id"
CONF_SPARKY_VERIFY_SSL = "verify_ssl"
CONF_SPARKY_POLL_INTERVAL = "poll_interval_minutes"
CONF_SPARKY_PUSH_EXERCISE = "sparkyfitness_push_exercise"
CONF_ENABLE_MANUAL_ENTRY = "enable_manual_entry"

DEFAULT_SPARKY_POLL_INTERVAL = 15
SPARKY_POLL_INTERVAL_MIN = 5
SPARKY_POLL_INTERVAL_MAX = 120

# SparkyFitness endpoint paths. Centralized so instances with a diverging
# API layout only need edits here (schema mapping lives in sparkyfitness.py).
SPARKY_FOOD_DIARY_PATH = "/api/food-entries"
SPARKY_EXERCISE_PATH = "/api/exercise-entries"

SPARKY_STALE_HOURS = 6  # unreachable this long -> incomplete_logging

# Nutrition goals
CONF_WEIGHT_GOAL_MODE = "weight_goal_mode"
WEIGHT_GOAL_LOSS = "loss"
WEIGHT_GOAL_MAINTENANCE = "maintenance"
WEIGHT_GOAL_GAIN = "gain"
WEIGHT_GOAL_MODES = [WEIGHT_GOAL_LOSS, WEIGHT_GOAL_MAINTENANCE, WEIGHT_GOAL_GAIN]

CONF_TARGET_DAILY_DEFICIT = "target_daily_deficit_kcal"
DEFAULT_TARGET_DAILY_DEFICIT = 500

CONF_MIN_INTAKE_FLOOR = "minimum_intake_floor_kcal"
INTAKE_FLOOR_FEMALE = 1200
INTAKE_FLOOR_MALE = 1500

CONF_PROTEIN_BASIS = "protein_target_basis"
PROTEIN_BASIS_TBW = "total_body_weight"
PROTEIN_BASIS_FFM = "fat_free_mass"
PROTEIN_BASIS_ABSOLUTE = "absolute_grams"
PROTEIN_BASES = [PROTEIN_BASIS_TBW, PROTEIN_BASIS_FFM, PROTEIN_BASIS_ABSOLUTE]

CONF_PROTEIN_G_PER_KG = "protein_target_g_per_kg"
DEFAULT_PROTEIN_G_PER_KG = 1.4
CONF_PROTEIN_G_PER_KG_FFM = "protein_target_g_per_kg_ffm"
DEFAULT_PROTEIN_G_PER_KG_FFM = 1.5
CONF_PROTEIN_ABSOLUTE_G = "protein_target_absolute_g"
DEFAULT_PROTEIN_ABSOLUTE_G = 100
CONF_PER_MEAL_PROTEIN_G = "per_meal_protein_target_g"
DEFAULT_PER_MEAL_PROTEIN_G = 28

CONF_TEF_MODE = "tef_calculation_mode"
TEF_MODE_FLAT = "flat_10_percent"
TEF_MODE_MACRO = "macronutrient_specific"
TEF_MODES = [TEF_MODE_MACRO, TEF_MODE_FLAT]

CONF_PROTEIN_CORRECTION_PCT = "protein_underreporting_correction_pct"
DEFAULT_PROTEIN_CORRECTION_PCT = 0

CONF_ADAPTIVE_THERMO = "adaptive_thermogenesis_enabled"
CONF_DEFICIT_CUTOFF_HOUR = "deficit_cutoff_hour"
DEFAULT_DEFICIT_CUTOFF_HOUR = 20
CONF_DYNAMIC_RMR_ENTITY = "dynamic_rmr_entity"
DYNAMIC_RMR_MAX_AGE_HOURS = 24

# Thermic effect of food coefficients (fraction of macro energy).
TEF_PROTEIN_COEFFICIENT = 0.25
TEF_CARB_COEFFICIENT = 0.075
TEF_FAT_COEFFICIENT = 0.02
KCAL_PER_G_PROTEIN = 4
KCAL_PER_G_CARB = 4
KCAL_PER_G_FAT = 9
TEF_FLAT_FRACTION = 0.10
TEF_MACRO_COVERAGE_MIN = 0.80  # fall back to flat below this coverage

# Deficit classification bands (kcal/day of deficit).
DEFICIT_MINIMAL_MAX = 249
DEFICIT_GUIDELINE_MAX = 750
DEFICIT_AGGRESSIVE_MAX = 1000

INCOMPLETE_INTAKE_THRESHOLD_KCAL = 500
IMPLAUSIBLE_INTAKE_KCAL = 10000
IMPLAUSIBLE_PROTEIN_G = 500

PROTEIN_CRITICAL_LOW_G_PER_KG = 0.5
PROTEIN_HIGH_ADVISORY_G_PER_KG = 2.0

# Meal buckets for timestamp inference when SparkyFitness omits the meal.
MEAL_BREAKFAST = "breakfast"
MEAL_LUNCH = "lunch"
MEAL_DINNER = "dinner"
MEAL_SNACK = "snack"
MEAL_UNKNOWN = "unknown"

# Extra services
SERVICE_LOG_FOOD = "log_food"
SERVICE_SET_PROTEIN_TARGET = "set_protein_target"
SERVICE_SET_DEFICIT_TARGET = "set_deficit_target"
SERVICE_SYNC_SPARKYFITNESS = "sync_sparkyfitness_now"
SERVICE_CLEAR_FOOD_LOG = "clear_todays_food_log"

# 2011 Compendium of Physical Activities MET values.
MET_VALUES: dict[str, float] = {
    "walking_slow_2mph": 2.5,
    "walking_moderate_3mph": 3.3,
    "walking_brisk_4mph": 5.0,
    "jogging_5mph": 7.0,
    "running_6mph": 9.8,
    "running_7mph": 11.0,
    "running_8mph": 11.8,
    "cycling_moderate_12mph": 8.0,
    "cycling_vigorous_16mph": 10.0,
    "swimming_moderate": 6.0,
    "swimming_vigorous": 9.8,
    "weight_training_moderate": 3.5,
    "weight_training_vigorous": 6.0,
    "yoga": 2.5,
    "hiit_circuit": 8.0,
    "rowing_machine": 7.0,
    "elliptical": 5.0,
    "stair_climbing": 9.0,
    "dancing": 5.5,
    "hiking": 6.0,
    "jump_rope": 12.3,
}
