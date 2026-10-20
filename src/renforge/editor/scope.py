"""Optional write scope for the Live Editor.

``RENFORGE_ALLOW_PATHS`` narrows which files inside ``game/`` a save or undo
may touch. It is a comma-separated list of game-relative POSIX glob patterns:

* ``*``, ``?`` and ``[...]`` match inside one path segment and never cross
  ``/`` (unlike plain ``fnmatch`` on the whole path).
* ``**`` as a whole segment matches zero or more directories.

When the variable is unset or blank, no extra scope applies and the fixed
``game/`` confinement in :mod:`renforge.editor.paths` is the only rule.
Invalid patterns fail closed: every commit and undo is refused with
``PATH_SCOPE_INVALID`` until the environment is fixed.
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from .exceptions import EditorError
from .paths import (
    EditorPathError,
    _validate_relative_path,
    resolve_game_path,
    to_game_relative_path,
)

ENV_ALLOW_PATHS = "RENFORGE_ALLOW_PATHS"


def load_path_scope(env: Mapping[str, str] | None = None) -> tuple[str, ...] | None:
    """Return the validated glob patterns, or ``None`` when no scope is set."""
    raw = (os.environ if env is None else env).get(ENV_ALLOW_PATHS)
    patterns = [part.strip() for part in (raw or "").split(",") if part.strip()]
    if not patterns:
        return None

    scope: list[str] = []
    for pattern in patterns:
        try:
            normalized = _validate_relative_path(pattern)
        except EditorPathError as exc:
            raise EditorError(
                "PATH_SCOPE_INVALID",
                f"invalid {ENV_ALLOW_PATHS} pattern {pattern!r}: {exc}",
                details={"pattern": pattern, "reason": exc.code},
            ) from exc
        scope.append(normalized.as_posix())
    return tuple(scope)


def is_path_in_scope(relative_path: str, scope: Sequence[str]) -> bool:
    """True when a game-relative POSIX path matches at least one pattern."""
    parts = relative_path.split("/")
    return any(_match_parts(pattern.split("/"), parts) for pattern in scope)


def _match_parts(pattern_parts: list[str], path_parts: list[str]) -> bool:
    if not pattern_parts:
        return not path_parts
    head = pattern_parts[0]
    rest = pattern_parts[1:]
    if head == "**":
        return _match_parts(rest, path_parts) or (
            bool(path_parts) and _match_parts(pattern_parts, path_parts[1:])
        )
    if not path_parts:
        return False
    if not fnmatch.fnmatchcase(path_parts[0], head):
        return False
    return _match_parts(rest, path_parts[1:])


def require_in_scope(project_root: str | Path, relative_path: str) -> None:
    """Refuse a write target outside ``RENFORGE_ALLOW_PATHS``.

    The target is re-resolved exactly like the editor's write path, so the
    decision is made on the real in-game file rather than on a caller-supplied
    string. Does nothing when the variable is unset.
    """
    scope = load_path_scope()
    if scope is None:
        return

    try:
        resolved = resolve_game_path(project_root, relative_path)
        relative = to_game_relative_path(project_root, resolved)
    except EditorPathError as exc:
        raise EditorError(exc.code, str(exc), details=dict(exc.details)) from exc

    if is_path_in_scope(relative, scope):
        return
    raise EditorError(
        "PATH_OUT_OF_SCOPE",
        f"path {relative} is outside the active editor write scope: {', '.join(scope)}",
        details={"path": relative, "scope": list(scope)},
    )
