"""widen detections.embedding to 1024-dim (DINOv2-L) for re-ID

Revision ID: 0003_reid_embedding
Revises: 0002_image_review
Create Date: 2026-06-14

The DeepFaune backbone (vit_large_patch14_dinov2) emits 1024-dim features. On the
native build the embedding column is a plain JSONB list created by 0001, so there
is no fixed-width pgvector column to widen — this migration is now a no-op kept
only to preserve alembic history.
"""

revision = "0003_reid_embedding"
down_revision = "0002_image_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass  # no-op: embedding is JSONB now (pgvector dropped for the native build)


def downgrade() -> None:
    pass  # no-op: embedding is JSONB now (pgvector dropped for the native build)
