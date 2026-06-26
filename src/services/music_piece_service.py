"""Service layer for MusicPiece CRUD operations and business logic."""

from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from src.database.models import MusicPiece, Translation, TranslationKind


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
        page = max(0, page)
        query = db.query(MusicPiece)

        if search:
            # Escape SQL LIKE metacharacters so user input is treated literally
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
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

    @staticmethod
    def set_primary_translation_pl(
        db: Session, piece_id: int, text: Optional[str]
    ) -> Optional[MusicPiece]:
        """Upsert the primary Polish translation, keeping the legacy column in sync.

        Writes the text to both:
        - ``MusicPiece.lyrics_translation_pl`` (legacy column, for backwards compatibility)
        - The ``Translation`` table row with ``language="pl"`` and ``is_primary=True``

        When *text* is empty or None the primary Translation row is deleted (if it
        exists) and the legacy column is set to None.  All other ``pl`` rows for the
        same piece have ``is_primary`` forced to False so that
        ``MusicPiece.primary_translation_pl`` is never ambiguous.

        Caller is responsible for committing via ``get_db_session``.

        Args:
            db: Active SQLAlchemy session.
            piece_id: Primary key of the piece to update.
            text: Translation text. Empty strings are normalised to None.

        Returns:
            Updated MusicPiece instance, or None if piece_id does not exist.
        """
        piece = db.query(MusicPiece).filter(MusicPiece.id == piece_id).first()
        if piece is None:
            return None

        text = (text or "").strip() or None

        # Always mirror to the legacy column so the fallback path stays correct.
        piece.lyrics_translation_pl = text

        # Load all existing Polish Translation rows for this piece.
        pl_rows = (
            db.query(Translation)
            .filter(Translation.music_piece_id == piece_id, Translation.language == "pl")
            .all()
        )

        primary = next((t for t in pl_rows if t.is_primary), None)

        if text is None:
            # Clear: remove the primary row; leave any non-primary rows untouched.
            if primary is not None:
                db.delete(primary)
        else:
            # Demote every *other* pl row that incorrectly carries is_primary=True
            # so we end up with exactly one primary.
            for row in pl_rows:
                if row is not primary and row.is_primary:
                    row.is_primary = False

            if primary is None:
                primary = Translation(
                    music_piece_id=piece.id,
                    language="pl",
                    is_primary=True,
                    kind=TranslationKind.LITERAL,
                    text=text,
                )
                db.add(primary)
            else:
                primary.text = text

        db.flush()
        return piece
