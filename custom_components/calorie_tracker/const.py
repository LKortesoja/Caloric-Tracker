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

# Config keys — goals
CONF_GOAL = "goal"
CONF_PROTEIN_MULTIPLIER = "protein_multiplier"

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
ATTR_FACTOR = "factor"
ATTR_WEIGHT_KG = "weight_kg"
ATTR_BODY_FAT_PCT = "body_fat_pct"

# Dispatcher signal (formatted with entry_id)
SIGNAL_UPDATE = f"{DOMAIN}_update_{{}}"

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
