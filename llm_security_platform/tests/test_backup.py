import tempfile
from pathlib import Path
from llm_security_platform.scripts.backup import backup_sqlite

def test_backup_sqlite():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_dir_path = Path(tmpdir)
        db_file = tmp_dir_path / "test.db"
        db_file.write_text("dummy database content")
        
        dest_dir = tmp_dir_path / "backups"
        dest_dir.mkdir()
        
        backup_file = backup_sqlite(db_file, dest_dir)
        
        assert backup_file is not None
        assert backup_file.exists()
        assert backup_file.read_text() == "dummy database content"
        assert backup_file.parent == dest_dir
