"""widen detections.embedding to 1024-dim (DINOv2-L) for re-ID

Revision ID: 0003_reid_embedding
Revises: 0002_image_review
Create Date: 2026-06-14

The DeepFaune backbone (vit_large_patch14_dinov2) emits 1024-dim features; the
initial schema created the column at 512. No embeddings were ever stored, so we
drop and recreate the column (and its HNSW cosine index) at the correct width.
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0003_reid_embedding"
down_revision = "0002_image_review"
branch_labels = None
depends_on = None

_IDX = "ix_detections_embedding_hnsw"


def _recreate(dim: int) -> None:
    op.drop_index(_IDX, table_name="detections")
    op.drop_column("detections", "embedding")
    op.add_column("detections", sa.Column("embedding", Vector(dim), nullable=True))
    op.create_index(
        _IDX, "detections", ["embedding"],
        postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def upgrade() -> None:
    _recreate(1024)


def downgrade() -> None:
    _recreate(512)
