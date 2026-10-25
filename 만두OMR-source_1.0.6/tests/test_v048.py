from datetime import datetime
from localomr import handoff
from test_math import store


def test_minute_backup_names_are_short_distinct_and_survive_reopen(store,monkeypatch):
    db,_=store
    class Clock:
        value=datetime(2026,10,19,19,22,59,999999)
        @classmethod
        def now(cls):return cls.value
    monkeypatch.setattr(handoff,'datetime',Clock)
    h=handoff.Handoff(db);before=db.db.total_changes
    assert h.filename()=='20261019_1922.omrbackup'
    assert h.filename()=='20261019_1922_2.omrbackup'
    h=handoff.Handoff(db)
    assert h.filename()=='20261019_1922_3.omrbackup'
    Clock.value=datetime(2026,10,19,19,23)
    assert h.filename()=='20261019_1923.omrbackup'
    assert not h.needs_backup() and db.db.total_changes==before
    # The optional, explicitly entered PC label remains supported.
    h.state['location']='중계/김조교'
    assert h.filename()=='20261019_1923_중계_김조교.omrbackup'
