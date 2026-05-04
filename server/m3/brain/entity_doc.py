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


def _fold_body(primary: str, secondary: str) -> str:
    """Join two entity bodies with a `---` separator. Empty sides collapse cleanly."""
    a = (primary or "").rstrip()
    b = (secondary or "").strip()
    if not a and not b:
        return ""
    if not a:
        return b + "\n"
    if not b:
        return a + "\n"
    return a + "\n\n---\n\n" + b + "\n"


def consolidate(
    root: Path,
    *,
    canonical_name: str,
    entity_type: str,
    merge_aliases: list[str] | None = None,
    description: str | None = None,
    related: list[str] | None = None,
    summary_external: str | None = None,
    body: str | None = None,
    match_existing_slug: str | None = None,
) -> Path:
    """Write ``canonical_name`` and fold any matching alias files into it.

    - If ``match_existing_slug`` is given and differs from ``slugify(canonical_name)``,
      the file at that slug is renamed: its body/aliases/related/signal_mentions are
      folded into the new file and the old file is removed. The old canonical name
      is added to the merged aliases.
    - Every alias in ``merge_aliases`` whose ``slugify`` points at a real file (and
      isn't already the new canonical slug) is folded in the same way and deleted.
    - If neither rename nor alias-fold happens, this behaves like a normal upsert.

    Returns the path of the final consolidated entity file.
    """
    p = BrainPaths(root)
    merge_aliases = list(merge_aliases or [])
    related = list(related or [])
    body = body or ""

    new_slug = slugify(canonical_name)
    collected_aliases: set[str] = set(merge_aliases)
    collected_related: set[str] = set(related)
    folded_signal_mentions = 0
    folded_body = body

    # Collect every slug we want to fold INTO the new file and then delete.
    absorb_slugs: list[str] = []
    if match_existing_slug and match_existing_slug != new_slug:
        absorb_slugs.append(match_existing_slug)
    for alias in merge_aliases:
        alias_slug = slugify(alias)
        if alias_slug == new_slug:
            continue
        if alias_slug in absorb_slugs:
            continue
        if p.entity_path(alias_slug).exists():
            absorb_slugs.append(alias_slug)

    for slug in absorb_slugs:
        existing = load(root, slug=slug)
        if existing is None:
            continue
        # Preserve the old canonical_name as an alias so searches still resolve.
        collected_aliases.add(existing.canonical_name)
        collected_aliases.update(existing.aliases)
        collected_related.update(existing.related)
        folded_signal_mentions += existing.signal_mentions
        folded_body = _fold_body(folded_body, existing.body)
        # Remove the absorbed file now; upsert will write the new one.
        p.entity_path(slug).unlink()

    # Merge in anything already at the destination slug (normal upsert semantics).
    dest_existing = load(root, slug=new_slug)
    if dest_existing is not None:
        collected_aliases.update(dest_existing.aliases)
        collected_related.update(dest_existing.related)
        folded_signal_mentions += dest_existing.signal_mentions
        folded_body = _fold_body(folded_body, dest_existing.body)
        description = description if description is not None else dest_existing.description
        summary_external = summary_external if summary_external is not None else dest_existing.summary_external

    # The new canonical name itself shouldn't appear in its own alias list.
    collected_aliases.discard(canonical_name)

    final = EntityDoc(
        canonical_name=canonical_name,
        entity_type=entity_type,
        aliases=sorted(collected_aliases),
        description=description,
        related=sorted(collected_related),
        signal_mentions=folded_signal_mentions,
        summary_external=summary_external,
        body=folded_body,
    )

    # Write directly (we've already merged everything we care about — don't let
    # upsert's own merge logic re-merge against a stale dest_existing).
    post = frontmatter.Post(final.body, **final.to_frontmatter_dict())
    path = p.entity_path(new_slug)
    path.write_text(frontmatter.dumps(post) + "\n")
    return path
