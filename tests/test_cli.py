import fcntl
import subprocess
import sys


def test_second_run_on_same_database_is_refused(tmp_path):
    db = tmp_path / "events.db"
    with db.with_suffix(".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        run = subprocess.run(
            [
                sys.executable,
                "-c",
                "from delay_ai.cli import main; main()",
                "--db",
                str(db),
                "outbox",
            ],
            capture_output=True,
            text=True,
        )
    assert run.returncode == 1
    assert "Another delay-ai run is using this database" in run.stderr
