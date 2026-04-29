from .exceptions import HarnessValidationError

CURRENT_SCHEMA_VERSION = 1

VALID_DRIVERS = {"llm", "script", "service", "hybrid"}

REQUIRED_FIELDS = {"name", "type", "driver"}

LLM_REQUIRED = {"model", "identity"}

SCRIPT_FORBIDDEN = {"model"}


def validate(harness: dict, filename: str) -> None:
    if "schema_version" not in harness:
        raise HarnessValidationError(
            f"{filename}: missing required field 'schema_version'"
        )
    version = harness["schema_version"]
    if not isinstance(version, int):
        raise HarnessValidationError(
            f"{filename}: 'schema_version' must be an integer, got {type(version).__name__}"
        )
    if version < CURRENT_SCHEMA_VERSION:
        raise HarnessValidationError(
            f"{filename}: schema out of date — found schema_version {version}, expected {CURRENT_SCHEMA_VERSION}"
        )
    if version > CURRENT_SCHEMA_VERSION:
        raise HarnessValidationError(
            f"{filename}: schema version {version} is newer than loader supports ({CURRENT_SCHEMA_VERSION})"
        )

    missing = REQUIRED_FIELDS - harness.keys()
    if missing:
        raise HarnessValidationError(
            f"{filename}: missing required fields: {missing}"
        )

    driver = harness.get("driver")
    if driver not in VALID_DRIVERS:
        raise HarnessValidationError(
            f"{filename}: invalid driver '{driver}'. Must be one of {VALID_DRIVERS}"
        )

    if driver == "llm":
        missing_llm = LLM_REQUIRED - harness.keys()
        if missing_llm:
            raise HarnessValidationError(
                f"{filename}: llm driver requires fields: {missing_llm}"
            )

    if driver == "script":
        present_forbidden = SCRIPT_FORBIDDEN & harness.keys()
        if present_forbidden:
            raise HarnessValidationError(
                f"{filename}: script driver must not include fields: {present_forbidden}"
            )

    routing = harness.get("routing", [])
    for i, rule in enumerate(routing):
        if "if" not in rule or "then" not in rule:
            raise HarnessValidationError(
                f"{filename}: routing rule {i} missing 'if' or 'then'"
            )

    guardrails = harness.get("guardrails", {})
    hard_stops = guardrails.get("hard_stops", [])
    if not isinstance(hard_stops, list):
        raise HarnessValidationError(
            f"{filename}: guardrails.hard_stops must be a list"
        )
