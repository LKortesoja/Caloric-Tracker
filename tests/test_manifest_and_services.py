"""Packaging checks that mirror what Home Assistant's hassfest enforces.

These caught a real CI failure: hassfest requires every service *field*
to carry a description, not just a name. Running the same rules locally
means the mistake surfaces in `pytest` instead of a red check on GitHub.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

COMPONENT = Path(__file__).resolve().parent.parent / "custom_components" / "calorie_tracker"

MANIFEST = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
SERVICES = yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8"))
STRINGS = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
TRANSLATIONS = json.loads(
    (COMPONENT / "translations" / "en.json").read_text(encoding="utf-8")
)
INIT_SOURCE = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
CONST_SOURCE = (COMPONENT / "const.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# File encoding
#
# A UTF-8 BOM crashed hassfest: it calls ast.parse(path.read_text()), which
# chokes on U+FEFF even though Python's own import machinery tolerates it.
# Windows editors and PowerShell's `Set-Content -Encoding utf8` add one
# silently, so this is worth asserting rather than trusting.
# ---------------------------------------------------------------------------

TEXT_FILES = sorted(
    p
    for ext in ("*.py", "*.json", "*.yaml", "*.yml", "*.md")
    for p in REPO_ROOT.rglob(ext)
    if not any(
        part in {".git", "__pycache__", ".pytest_cache", ".ruff_cache"}
        for part in p.parts
    )
)


@pytest.mark.parametrize(
    "path", TEXT_FILES, ids=[str(p.relative_to(REPO_ROOT)) for p in TEXT_FILES]
)
def test_file_has_no_byte_order_mark(path):
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf"), (
        f"{path.relative_to(REPO_ROOT)} starts with a UTF-8 BOM; "
        "rewrite it as UTF-8 without BOM"
    )


@pytest.mark.parametrize(
    "path",
    [p for p in TEXT_FILES if p.suffix == ".py"],
    ids=[str(p.relative_to(REPO_ROOT)) for p in TEXT_FILES if p.suffix == ".py"],
)
def test_module_parses_the_way_hassfest_parses_it(path):
    """hassfest walks the AST of every module; mirror that exactly."""
    ast.parse(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# manifest.json
# ---------------------------------------------------------------------------


def test_manifest_required_keys():
    for key in ("domain", "name", "version", "documentation", "codeowners"):
        assert key in MANIFEST, f"manifest.json is missing '{key}'"


def test_manifest_domain_matches_folder():
    assert MANIFEST["domain"] == COMPONENT.name


def test_manifest_key_order():
    """hassfest requires domain, then name, then the rest alphabetically."""
    keys = list(MANIFEST)
    assert keys[0] == "domain"
    assert keys[1] == "name"
    assert keys[2:] == sorted(keys[2:])


def test_manifest_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", MANIFEST["version"])


def test_codeowners_format():
    for owner in MANIFEST["codeowners"]:
        assert owner.startswith("@"), f"codeowner {owner} must start with @"


def test_iot_class_and_integration_type_are_valid():
    assert MANIFEST["iot_class"] in {
        "assumed_state", "cloud_polling", "cloud_push",
        "local_polling", "local_push", "calculated",
    }
    assert MANIFEST["integration_type"] in {
        "device", "entity", "hardware", "helper", "hub", "service", "system",
    }


# ---------------------------------------------------------------------------
# services.yaml — the rules that broke CI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("service", sorted(SERVICES))
def test_service_has_name_and_description(service):
    schema = SERVICES[service] or {}
    assert schema.get("name"), f"service '{service}' needs a name"
    assert schema.get("description"), f"service '{service}' needs a description"


def _iter_fields():
    for service, schema in SERVICES.items():
        for field, field_schema in ((schema or {}).get("fields") or {}).items():
            yield service, field, field_schema or {}


@pytest.mark.parametrize(
    ("service", "field", "schema"),
    [pytest.param(s, f, sc, id=f"{s}.{f}") for s, f, sc in _iter_fields()],
)
def test_service_field_has_name_and_description(service, field, schema):
    """hassfest errors when a field lacks either of these."""
    assert schema.get("name"), f"{service}.{field} needs a name"
    assert schema.get("description"), f"{service}.{field} needs a description"


def test_registered_services_are_documented():
    """Every service registered in code must appear in services.yaml."""
    constants = dict(
        re.findall(r'^(SERVICE_[A-Z_]+)\s*=\s*"([^"]+)"', CONST_SOURCE, re.MULTILINE)
    )
    registered = {
        constants[name]
        for name in re.findall(r"DOMAIN,\s*(SERVICE_[A-Z_]+)", INIT_SOURCE)
        if name in constants
    }
    assert registered, "no registered services were detected"
    missing = registered - set(SERVICES)
    assert not missing, f"registered but undocumented in services.yaml: {missing}"


def test_no_orphan_service_documentation():
    constants = dict(
        re.findall(r'^(SERVICE_[A-Z_]+)\s*=\s*"([^"]+)"', CONST_SOURCE, re.MULTILINE)
    )
    documented_but_unregistered = set(SERVICES) - set(constants.values())
    assert not documented_but_unregistered, (
        f"documented but never registered: {documented_but_unregistered}"
    )


# ---------------------------------------------------------------------------
# strings.json / translations
# ---------------------------------------------------------------------------


def test_translations_match_strings():
    """translations/en.json must stay in sync with strings.json."""
    assert TRANSLATIONS == STRINGS, (
        "translations/en.json is out of date — copy strings.json over it"
    )


def test_every_config_step_has_a_title():
    for step, content in STRINGS["config"]["step"].items():
        assert content.get("title"), f"config step '{step}' has no title"


def test_config_flow_errors_are_translated():
    """Error keys raised by the config flow must exist in strings.json."""
    flow_source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    raised = set(re.findall(r'errors\[[^\]]+\]\s*=\s*"([a-z_]+)"', flow_source))
    # Errors returned by the shared validation helper.
    raised.update(re.findall(r'^\s+return "([a-z_]+)"', flow_source, re.MULTILINE))
    translated = set(STRINGS["config"].get("error", {}))
    missing = raised - translated
    assert not missing, f"untranslated config flow errors: {missing}"


def test_entity_translation_keys_exist_for_every_sensor():
    """Each sensor/binary_sensor translation_key needs a name entry."""
    for platform in ("sensor", "binary_sensor"):
        source = (COMPONENT / f"{platform}.py").read_text(encoding="utf-8")
        keys = set(re.findall(r'translation_key="([a-z0-9_]+)"', source))
        named = set(STRINGS["entity"][platform])
        missing = keys - named
        assert not missing, f"{platform} keys missing from strings.json: {missing}"
