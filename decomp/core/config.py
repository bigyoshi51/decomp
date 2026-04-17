from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator


class DecompConfig(BaseModel):
    """Configuration for connecting to an existing N64 decomp project."""

    # Project paths. project_root defaults to the config file's directory
    # when loaded via load(); base_rom is resolved relative to project_root.
    project_root: Path = Path(".")
    base_rom: Path = Path("baserom.z64")

    # Optional targeting
    target_function: str | None = None  # Specific function to decompile

    # Tool paths
    ido_recomp: Path = Path("ido-static-recomp")  # Path to ido-static-recomp build dir
    permuter: Path | None = None  # Optional: path to decomp-permuter clone

    # Agent settings
    max_attempts: int = 30
    model: str = "claude-opus-4-6"

    # Project structure paths (relative to project_root)
    asm_dir: Path = Path("asm/non_matchings")
    src_dir: Path = Path("src")
    include_dir: Path = Path("include")

    @model_validator(mode="after")
    def resolve_relative_paths(self) -> DecompConfig:
        """Resolve project-relative paths against project_root."""
        root = self.project_root
        for field in ("asm_dir", "src_dir", "include_dir"):
            path = getattr(self, field)
            if not path.is_absolute():
                object.__setattr__(self, field, root / path)
        if not self.base_rom.is_absolute():
            self.base_rom = root / self.base_rom
        return self

    @classmethod
    def load(cls, path: Path) -> DecompConfig:
        """Load config from a decomp.yaml or decomp.toml file.

        If `project_root` is not set (or is a relative path), resolve it
        relative to the config file's directory so the project is portable.
        """
        text = path.read_text()
        if path.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(text) or {}
        elif path.suffix == ".toml":
            import tomllib

            data = tomllib.loads(text)
        else:
            raise ValueError(f"Unsupported config format: {path.suffix}")
        config_dir = path.resolve().parent
        root = Path(data.get("project_root", "."))
        data["project_root"] = root if root.is_absolute() else config_dir / root
        return cls(**data)

    def for_worktree(self, wt_path: Path) -> DecompConfig:
        """Return a copy of this config with all paths re-rooted at wt_path."""
        orig = self.project_root
        updates: dict = {"project_root": wt_path}
        for field in ("asm_dir", "src_dir", "include_dir"):
            path = getattr(self, field)
            if path.is_absolute():
                try:
                    updates[field] = wt_path / path.relative_to(orig)
                except ValueError:
                    pass  # not under project_root, leave unchanged
        if self.base_rom.is_absolute():
            try:
                updates["base_rom"] = wt_path / self.base_rom.relative_to(orig)
            except ValueError:
                pass
        return self.model_copy(update=updates)

    @classmethod
    def find_and_load(cls, start: Path | None = None) -> DecompConfig:
        """Search for decomp.yaml/decomp.toml starting from `start` and walking up."""
        search = start or Path.cwd()
        for directory in [search, *search.parents]:
            for name in ("decomp.yaml", "decomp.yml", "decomp.toml"):
                candidate = directory / name
                if candidate.exists():
                    return cls.load(candidate)
        raise FileNotFoundError(
            "No decomp.yaml or decomp.toml found in current directory or parents"
        )
