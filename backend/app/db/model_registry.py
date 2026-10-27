"""Central import point for every ORM model module.

SQLAlchemy's declarative registry — and therefore `Base.metadata` and
any cross-module `relationship("SomeClass", ...)` string reference —
only knows about a model class once its module has been imported
somewhere in the running process. Alembic's `env.py` and every module's
test suite import *this* module rather than remembering to import each
model module individually, so nothing has to keep that list in sync by
hand in more than one place.

Every future module's models.py is added here as it's created.
"""

from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.chat import models as _chat_models  # noqa: F401
from app.modules.documents import models as _documents_models  # noqa: F401
from app.modules.documents import chunks as _documents_chunks  # noqa: F401
from app.modules.workspaces import models as _workspaces_models  # noqa: F401
