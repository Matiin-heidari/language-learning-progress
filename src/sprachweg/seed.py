"""Thin convenience wrappers around the language catalog (see
services/language_catalog.py for the actual templates/levels/skill-mix data
and the create/clone logic). Kept as a separate module because it's the
stable, well-known entry point CLI commands and tests import from.
"""

from __future__ import annotations

from sprachweg.models import Language, User
from sprachweg.services.language_catalog import (
    clone_template_for_user,
    ensure_german_template,
    seed_global_activity_types,
)

__all__ = ["seed_global_activity_types", "seed_user_language"]


def seed_user_language(user: User, *, code: str = "de") -> Language:
    """Give `user` a language cloned from the catalog. Only "de" (German) is
    guaranteed to exist in the catalog out of the box; other codes require
    an admin to have added that template first (Admin -> Language catalog).
    Idempotent per (user, code).
    """
    if code == "de":
        template = ensure_german_template()
    else:
        from sprachweg.services.language_catalog import list_language_templates

        template = next((t for t in list_language_templates() if t.code == code), None)
        if template is None:
            raise ValueError(f"No '{code}' template in the language catalog yet.")
    return clone_template_for_user(user, template)
