"""Load and validate `.devin/qa.toml`."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigError

CONFIG_RELATIVE_PATH = Path(".devin") / "qa.toml"
PLATFORMS = ("ios", "android", "macos", "linux", "windows", "web")
DEFAULT_VM = {
    "ios": "macos",
    "android": "linux",
    "macos": "macos",
    "linux": "linux",
    "windows": "windows",
    "web": "linux",
}
SEVERITIES = ("blocker", "critical", "major", "minor", "cosmetic")
PRIORITIES = ("p0", "p1")
DELIVERY_MODES = ("push", "bundle")


@dataclass(frozen=True)
class PlatformSpec:
    name: str
    vm: str
    setup: str
    build: str
    test: str
    app_id: str
    artifact: str
    launch: str
    devices: tuple[str, ...]
    window_sizes: tuple[str, ...]
    notes: str
    themes: tuple[str, ...] = ()       # empty = inherit [layout]
    locales: tuple[str, ...] = ()
    text_scale: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    priority: str
    platforms: tuple[str, ...]
    steps: str
    expect: str
    paths: tuple[str, ...]

    def applies_to(self, platform: str) -> bool:
        return not self.platforms or platform in self.platforms


@dataclass(frozen=True)
class RunSettings:
    default_platforms: tuple[str, ...]
    max_rounds: int
    timeout_minutes: int
    poll_seconds: int
    max_parallel: int
    reuse_sessions: bool
    devin_mode: str
    max_acu_limit: int
    fail_on: frozenset[str]
    record_video: bool
    download_videos: bool


@dataclass(frozen=True)
class Layout:
    themes: tuple[str, ...]
    locales: tuple[str, ...]
    text_scale: tuple[str, ...]
    checks: str


@dataclass(frozen=True)
class Config:
    path: Path
    root: Path
    product_name: str
    product_summary: str
    repo: str
    delivery_mode: str
    scratch_prefix: str
    remote: str
    run: RunSettings
    release_command: tuple[str, ...]  # argv, executed without a shell
    release_auto: bool
    devin_secret_names: tuple[str, ...]
    secrets_from_env: tuple[str, ...]
    layout: Layout
    platforms: dict[str, PlatformSpec]
    scenarios: tuple[Scenario, ...]


TOP_KEYS = {"schema", "product", "delivery", "run", "release", "secrets", "layout", "platforms", "scenarios"}
SECTION_KEYS = {
    "product": {"name", "summary", "repo"},
    "delivery": {"mode", "scratch_prefix", "remote"},
    "run": {
        "default_platforms", "max_rounds", "timeout_minutes", "poll_seconds", "max_parallel",
        "reuse_sessions", "devin_mode", "max_acu_limit", "fail_on", "record_video", "download_videos",
    },
    "release": {"command", "auto"},
    "secrets": {"devin_secret_names", "from_env"},
    "layout": {"themes", "locales", "text_scale", "checks"},
}
PLATFORM_KEYS = {
    "vm", "setup", "build", "test", "app_id", "artifact", "launch", "devices", "window_sizes", "notes",
    "themes", "locales", "text_scale",
}
SCENARIO_KEYS = {"id", "title", "priority", "platforms", "steps", "expect", "paths"}


class _Reader:
    """Typed accessors that name the offending key in every error."""

    def __init__(self, table: dict[str, Any], where: str, allowed: set[str]):
        unknown = sorted(set(table) - allowed)
        if unknown:
            raise ConfigError(f"{where}: unknown key(s) {', '.join(unknown)}")
        self.table = table
        self.where = where

    def string(self, key: str, default: str = "", required: bool = False) -> str:
        if key not in self.table:
            if required:
                raise ConfigError(f"{self.where}.{key} is required")
            return default
        value = self.table[key]
        if not isinstance(value, str):
            raise ConfigError(f"{self.where}.{key} must be a string")
        if required and not value.strip():
            raise ConfigError(f"{self.where}.{key} must not be empty")
        return value.strip()

    def integer(self, key: str, default: int, minimum: int) -> int:
        value = self.table.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ConfigError(f"{self.where}.{key} must be an integer >= {minimum}")
        return value

    def boolean(self, key: str, default: bool) -> bool:
        value = self.table.get(key, default)
        if not isinstance(value, bool):
            raise ConfigError(f"{self.where}.{key} must be true or false")
        return value

    def strings(self, key: str, default: tuple[str, ...] = (), choices: tuple[str, ...] = ()) -> tuple[str, ...]:
        value = self.table.get(key, list(default))
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ConfigError(f"{self.where}.{key} must be a list of strings")
        items = tuple(v.strip() for v in value if v.strip())
        bad = [v for v in items if choices and v not in choices]
        if bad:
            raise ConfigError(f"{self.where}.{key}: {', '.join(bad)} not in {', '.join(choices)}")
        return items


def _section(data: dict[str, Any], name: str) -> _Reader:
    table = data.get(name, {})
    if not isinstance(table, dict):
        raise ConfigError(f"[{name}] must be a table")
    return _Reader(table, f"[{name}]", SECTION_KEYS[name])


def _platform(name: str, table: Any) -> PlatformSpec:
    if name not in PLATFORMS:
        raise ConfigError(f"[platforms.{name}]: unknown platform; use one of {', '.join(PLATFORMS)}")
    if not isinstance(table, dict):
        raise ConfigError(f"[platforms.{name}] must be a table")
    r = _Reader(table, f"[platforms.{name}]", PLATFORM_KEYS)
    return PlatformSpec(
        name=name,
        vm=r.string("vm", DEFAULT_VM[name]) or DEFAULT_VM[name],
        setup=r.string("setup"),
        build=r.string("build"),
        test=r.string("test"),
        app_id=r.string("app_id"),
        artifact=r.string("artifact"),
        launch=r.string("launch"),
        devices=r.strings("devices"),
        window_sizes=r.strings("window_sizes"),
        notes=r.string("notes"),
        themes=r.strings("themes"),
        locales=r.strings("locales"),
        text_scale=r.strings("text_scale"),
    )


def _scenario(index: int, table: Any) -> Scenario:
    where = f"[[scenarios]] #{index + 1}"
    if not isinstance(table, dict):
        raise ConfigError(f"{where} must be a table")
    r = _Reader(table, where, SCENARIO_KEYS)
    scenario_id = r.string("id", required=True)
    if not scenario_id.replace("-", "").replace("_", "").isalnum():
        raise ConfigError(f"{where}.id must use letters, digits, '-' or '_'")
    priority = r.string("priority", "p0") or "p0"
    if priority not in PRIORITIES:
        raise ConfigError(f"{where}.priority must be p0 or p1")
    return Scenario(
        id=scenario_id,
        title=r.string("title", scenario_id) or scenario_id,
        priority=priority,
        platforms=r.strings("platforms", choices=PLATFORMS),
        steps=r.string("steps", required=True),
        expect=r.string("expect", required=True),
        paths=r.strings("paths"),
    )


def find_config(root: Path) -> Path:
    path = root / CONFIG_RELATIVE_PATH
    if not path.is_file():
        raise ConfigError(f"{path} not found; run `client-validation-devin init` "
                          "(skill client-validation-devin-setup) first")
    return path


def load_config(root: Path, path: Path | None = None) -> Config:
    path = path or find_config(root)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc
    return parse_config(data, path=path, root=root)


def parse_config(data: dict[str, Any], *, path: Path, root: Path) -> Config:
    unknown = sorted(set(data) - TOP_KEYS)
    if unknown:
        raise ConfigError(f"{path.name}: unknown top-level key(s) {', '.join(unknown)}")
    if data.get("schema", 1) != 1:
        raise ConfigError(f"{path.name}: schema must be 1")

    product = _section(data, "product")
    delivery = _section(data, "delivery")
    run = _section(data, "run")
    release = _section(data, "release")
    secrets = _section(data, "secrets")
    layout = _section(data, "layout")

    platforms_table = data.get("platforms", {})
    if not isinstance(platforms_table, dict) or not platforms_table:
        raise ConfigError("[platforms.<name>] tables are required (at least one platform)")
    platforms = {name: _platform(name, table) for name, table in platforms_table.items()}

    scenario_list = data.get("scenarios", [])
    if not isinstance(scenario_list, list):
        raise ConfigError("[[scenarios]] must be an array of tables")
    scenarios = tuple(_scenario(i, t) for i, t in enumerate(scenario_list))
    ids = [s.id for s in scenarios]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ConfigError(f"[[scenarios]]: duplicate id(s) {', '.join(duplicates)}")

    mode = delivery.string("mode", "push") or "push"
    if mode not in DELIVERY_MODES:
        raise ConfigError("[delivery].mode must be push or bundle")
    scratch_prefix = delivery.string("scratch_prefix", "client-validation-devin/") or "client-validation-devin/"
    if not scratch_prefix.endswith("/"):
        scratch_prefix += "/"

    default_platforms = run.strings("default_platforms", tuple(platforms), choices=PLATFORMS)
    missing = [p for p in default_platforms if p not in platforms]
    if missing:
        raise ConfigError(f"[run].default_platforms lists {', '.join(missing)} without [platforms.*] tables")
    for spec in platforms.values():
        if not spec.build and spec.name != "web":
            raise ConfigError(f"[platforms.{spec.name}].build is required")

    settings = RunSettings(
        default_platforms=default_platforms or tuple(platforms),
        max_rounds=run.integer("max_rounds", 5, 1),
        timeout_minutes=run.integer("timeout_minutes", 90, 20),
        poll_seconds=run.integer("poll_seconds", 20, 5),
        max_parallel=run.integer("max_parallel", 5, 1),
        reuse_sessions=run.boolean("reuse_sessions", True),
        devin_mode=run.string("devin_mode"),
        max_acu_limit=run.integer("max_acu_limit", 0, 0),
        fail_on=frozenset(run.strings("fail_on", ("blocker", "critical", "major"), choices=SEVERITIES)),
        record_video=run.boolean("record_video", True),
        download_videos=run.boolean("download_videos", False),
    )
    return Config(
        path=path,
        root=root,
        product_name=product.string("name", required=True),
        product_summary=product.string("summary", required=True),
        repo=product.string("repo"),
        delivery_mode=mode,
        scratch_prefix=scratch_prefix,
        remote=delivery.string("remote", "origin") or "origin",
        run=settings,
        release_command=release.strings("command"),
        release_auto=release.boolean("auto", False),
        devin_secret_names=secrets.strings("devin_secret_names"),
        secrets_from_env=secrets.strings("from_env"),
        layout=Layout(
            themes=layout.strings("themes", ("light", "dark")),
            locales=layout.strings("locales", ("en",)),
            text_scale=layout.strings("text_scale", ("default", "largest")),
            checks=layout.string("checks"),
        ),
        platforms=platforms,
        scenarios=scenarios,
    )
