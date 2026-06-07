"""Service layer for MusicPiece CRUD operations and business logic."""

from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from src.database.models import MusicPiece


class MusicPieceService:
    """CRUD and business-logic operations for MusicPiece entities."""

    @staticmethod
    def list_pieces(
        db: Session,
        search: Optional[str] = None,
        occasion: Optional[str] = None,
        liturgical_season: Optional[str] = None,
        page: int = 0,
        per_page: int = 20,
    ) -> Tuple[List[MusicPiece], int]:
        """Return (items, total_count) with optional filtering and pagination.

        Args:
            db: Active SQLAlchemy session.
            search: Case-insensitive substring matched against title, composer,
                and lyrics_author.
            occasion: Exact match filter on occasion field.
            liturgical_season: Exact match filter on liturgical_season field.
            page: Zero-based page index.
            per_page: Number of records per page.

        Returns:
            Tuple of (list of MusicPiece, total matching count).
        """
        query = db.query(MusicPiece)

        if search:
            pattern = f"%{search}%"
            query = query.filter(
                MusicPiece.title.ilike(pattern)
                | MusicPiece.composer.ilike(pattern)
                | MusicPiece.lyrics_author.ilike(pattern)
            )

        if occasion:
            query = query.filter(MusicPiece.occasion == occasion)

        if liturgical_season:
            query = query.filter(MusicPiece.liturgical_season == liturgical_season)

        total_count = query.count()
        items = query.offset(page * per_page).limit(per_page).all()

        return items, total_count

    @staticmethod
    def get_piece(db: Session, piece_id: int) -> Optional[MusicPiece]:
        """Return MusicPiece by primary key, or None if not found.

        Args:
            db: Active SQLAlchemy session.
            piece_id: Primary key of the piece to retrieve.
        """
        return db.query(MusicPiece).filter(MusicPiece.id == piece_id).first()

    @staticmethod
    def create_piece(db: Session, **kwargs) -> MusicPiece:
        """Create and flush a new MusicPiece (caller commits via get_db_session).

        Args:
            db: Active SQLAlchemy session.
            **kwargs: Field values for MusicPiece. Unknown keys are ignored.

        Returns:
            Newly created MusicPiece instance (not yet committed).
        """
        valid_fields = {c.name for c in MusicPiece.__table__.columns}
        filtered = {k: v for k, v in kwargs.items() if k in valid_fields}
        piece = MusicPiece(**filtered)
        db.add(piece)
        db.flush()
        return piece

    @staticmethod
    def update_piece(db: Session, piece_id: int, **kwargs) -> Optional[MusicPiece]:
        """Update fields on an existing MusicPiece (caller commits via get_db_session).

        Unknown keys in kwargs are silently ignored.

        Args:
            db: Active SQLAlchemy session.
            piece_id: Primary key of the piece to update.
            **kwargs: Fields to update.

        Returns:
            Updated MusicPiece instance, or None if piece_id does not exist.
        """
        piece = db.query(MusicPiece).filter(MusicPiece.id == piece_id).first()
        if piece is None:
            return None

        valid_fields = {c.name for c in MusicPiece.__table__.columns} - {"id", "created_at"}
        for key, value in kwargs.items():
            if key in valid_fields:
                setattr(piece, key, value)

        db.flush()
        return piece

    @staticmethod
    def delete_piece(db: Session, piece_id: int) -> bool:
        """Delete a MusicPiece (cascade removes files and usage history).

        Args:
            db: Active SQLAlchemy session.
            piece_id: Primary key of the piece to delete.

        Returns:
            True if the piece existed and was deleted, False otherwise.
        """
        piece = db.query(MusicPiece).filter(MusicPiece.id == piece_id).first()
        if piece is None:
            return False
        db.delete(piece)
        db.flush()
        return True
