#!/usr/bin/env python
"""
LLM Security Platform - Automated Backup Script
Supports daily automated backups of SQLite and PostgreSQL databases.
Usage:
  python -m llm_security_platform.scripts.backup --dest backups
"""
import argparse
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from llm_security_platform.app.config import DATABASE_PATH, DATABASE_URL

def backup_sqlite(db_file: Path, dest_dir: Path) -> Path:
    if not db_file.exists():
        print(f"[-] SQLite database file not found at {db_file}, skipping.")
        return None
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = dest_dir / f"{db_file.stem}_backup_{timestamp}{db_file.suffix}"
    
    print(f"[*] Backing up SQLite database: {db_file} -> {backup_file}")
    shutil.copy2(db_file, backup_file)
    print("[+] SQLite backup completed successfully.")
    return backup_file

def backup_postgresql(db_url: str, dest_dir: Path) -> Path:
    print("[*] Detecting PostgreSQL environment for backup...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = dest_dir / f"postgres_backup_{timestamp}.sql"
    
    cleaned_url = db_url.replace("postgresql+psycopg://", "postgresql://")
    
    print(f"[*] Running pg_dump to {backup_file}...")
    try:
        cmd = ["pg_dump", cleaned_url, "-F", "p", "-f", str(backup_file)]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("[+] PostgreSQL backup completed successfully.")
        return backup_file
    except FileNotFoundError:
        print("[-] Warning: 'pg_dump' utility not found on PATH. Attempting fallback via Docker Compose...")
        try:
            cmd = ["docker", "compose", "exec", "-T", "postgres", "pg_dump", "-U", "llm_security", "-d", "llm_security"]
            backup_file_alt = dest_dir / f"postgres_backup_{timestamp}.sql"
            with open(backup_file_alt, "w", encoding="utf-8") as f:
                subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True, check=True)
            print(f"[+] PostgreSQL fallback docker-compose backup completed successfully: {backup_file_alt}")
            return backup_file_alt
        except Exception as e:
            print(f"[-] Fallback docker backup failed: {e}")
        return None
    except subprocess.CalledProcessError as e:
        print(f"[-] pg_dump failed with error code {e.returncode}: {e.stderr}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Backup utility for LLM Security Platform databases.")
    parser.add_argument("--dest", type=str, default="backups", help="Directory where backups will be stored.")
    args = parser.parse_args()
    
    dest_dir = Path(args.dest)
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Backup SQLite database files
    backup_sqlite(DATABASE_PATH, dest_dir)
    
    # Check if stage_five.db exists and backup if found
    stage_five_db = Path("llm_security_platform/stage_five.db")
    if stage_five_db.exists():
        backup_sqlite(stage_five_db, dest_dir)
        
    # 2. Check if PostgreSQL URL is configured
    if DATABASE_URL and (DATABASE_URL.startswith("postgresql") or "postgres" in DATABASE_URL):
        backup_postgresql(DATABASE_URL, dest_dir)
    else:
        print("[*] SQLite is configured. Skipping PostgreSQL backup.")

if __name__ == "__main__":
    main()
