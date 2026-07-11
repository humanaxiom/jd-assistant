"""JD Bank persistence — SQLAlchemy models on the shared harness ``Base``.

Importing this package registers every JD Bank table on
``src.models.db.Base.metadata`` (via :mod:`src.jd_bank.db.models`), so both
``Base.metadata.create_all`` and the Alembic autogenerate/target metadata see
the full schema.
"""

from src.jd_bank.db import models as models

__all__ = ["models"]
