from sqlalchemy.orm import Session

from rhapsode import models


def get_note(db: Session, segment_id: str) -> models.PersonalNote | None:
    return db.get(models.PersonalNote, segment_id)


def put_note(db: Session, segment_id: str, text: str) -> models.PersonalNote:
    if db.get(models.Segment, segment_id) is None:
        raise LookupError(segment_id)
    note = get_note(db, segment_id)
    if note is None:
        note = models.PersonalNote(segment_id=segment_id, text=text)
        db.add(note)
    else:
        note.text = text
    db.commit()
    return note
