"""Entity markdown files with YAML frontmatter. One file per entity under entities/<slug>.md."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

from m3.brain.layout import BrainPaths


@dataclass
class EntityDoc:
    canonical_name: str
    entity_type: str                       # free-form hint; not enforced
    aliases: list[str] = field(default_factory=list)
    description: str | None = None
    related: list[str] = field(default_factory=list)   # slugs
    signal_mentions: int = 0
    summary_external: str | None = None
    body: str = ""                         # markdown body after frontmatter

    def to_frontmatter_dict(self) -> dict:
        return {
            "canonical_name": self.canonical_name,
            "entity_type": self.entity_type,
            "aliases": list(self.aliases),
            "description": self.description,
            "related": list(self.related),
            "signal_mentions": self.signal_mentions,
            "summary_external": self.summary_external,
        }


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    lowered = name.strip().lower()
    slug = _SLUG_RE.sub("-", lowered).strip("-")
    return slug or "unnamed"


def load(root: Path, *, slug: str) -> EntityDoc | None:
    p = BrainPaths(root)
    path = p.entity_path(slug)
    if not path.exists():
        return None
    raw = path.read_text()
    post = frontmatter.loads(raw)
    meta = post.metadata
    body = post.content
    # Preserve a trailing newline from the original file, since frontmatter strips it.
    if raw.endswith("\n") and not body.endswith("\n"):
        body = body + "\n"
    return EntityDoc(
        canonical_name=meta.get("canonical_name", slug),
        entity_type=meta.get("entity_type", "topic"),
        aliases=list(meta.get("aliases") or []),
        description=meta.get("description"),
        related=list(meta.get("related") or []),
        signal_mentions=int(meta.get("signal_mentions") or 0),
        summary_external=meta.get("summary_external"),
        body=body,
    )


def upsert(root: Path, doc: EntityDoc) -> Path:
    """Create or update an entity file. Aliases merge as a set union; other fields overwrite."""
    p = BrainPaths(root)
    slug = slugify(doc.canonical_name)
    existing = load(root, slug=slug)
    if existing:
        merged_aliases = sorted(set(existing.aliases) | set(doc.aliases))
        merged_related = sorted(set(existing.related) | set(doc.related))
        final = EntityDoc(
            canonical_name=doc.canonical_name,
            entity_type=doc.entity_type or existing.entity_type,
            aliases=merged_aliases,
            description=doc.description if doc.description is not None else existing.description,
            related=merged_related,
            signal_mentions=doc.signal_mentions if doc.signal_mentions else existing.signal_mentions,
            summary_external=doc.summary_external if doc.summary_external is not None else existing.summary_external,
            body=doc.body or existing.body,
        )
    else:
        final = doc
    post = frontmatter.Post(final.body, **final.to_frontmatter_dict())
    path = p.entity_path(slug)
    path.write_text(frontmatter.dumps(post) + "\n")
    return path
