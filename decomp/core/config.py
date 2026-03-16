from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator


class DecompConfig(BaseModel):
    """Configuration for connecting to an existing N64 decomp project."""

    # Project paths
    project_root: Path  # Root of the decomp project (e.g., /path/to/sm64)
    base_rom: Path  # Path to base ROM

    # Optional targeting
    target_function: str | None = None  # Specific function to decompile

    # Tool paths
    ido_recomp: Path = Path("ido-static-recomp")  # Path to ido-static-recomp build dir
    permuter: Path | None = None  # Optional: path to decomp-permuter clone

    # Agent settings
    max_attempts: int = 30
    model: str = "claude-sonnet-4-20250514"

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
        """Load config from a decomp.yaml or decomp.toml file."""
        text = path.read_text()
        if path.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(text)
        elif path.suffix == ".toml":
            import tomllib

            data = tomllib.loads(text)
        else:
            raise ValueError(f"Unsupported config format: {path.suffix}")
        return cls(**data)

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
