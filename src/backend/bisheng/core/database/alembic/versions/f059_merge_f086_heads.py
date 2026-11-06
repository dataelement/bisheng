"""Join F059 schema extensions and the inherited F086 byte-counter widening.

No released parent is rewritten. Neither path changes application data.
"""

revision = "f059_merge_f086_heads"
down_revision = ("f059_runtime_kubernetes", "f086_runtime_byte_counters")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
