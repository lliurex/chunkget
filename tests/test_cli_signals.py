import os
import signal
import threading

import pytest

from chunkget import cli, manifest_builder
from chunkget import state as state_module
from chunkget import manifest as manifest_module

CONTENT = bytes(index % 251 for index in range(250))


@pytest.fixture
def slow(tmp_path, http_server, monkeypatch):
    """A 5-chunk download whose server delays every answer.

    Returns (manifest path, state dir, destination, server).
    """
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    source = tmp_path / "image.iso"
    source.write_bytes(CONTENT)
    url = http_server.serve("/image.iso", CONTENT)
    built = manifest_builder.build_manifest(source, url, chunk_size=50)
    path = tmp_path / "m.manifest"
    path.write_bytes(built.to_json().encode("utf-8"))
    http_server.delay("/image.iso", 0.3)
    return path, tmp_path / "state", tmp_path / "out.iso", http_server


def download(slow, *extra):
    path, state_dir, destination, _server = slow
    return cli.main(
        ["download", str(path), "-o", str(destination), "--state-dir", str(state_dir),
         *extra]
    )


def saved_states(slow):
    path, state_dir, destination, _server = slow
    loaded = manifest_module.load_manifest_file(path)
    return state_module.load_state(state_dir, loaded, destination).chunk_states


def signal_on_third_chunk(server, signum):
    server.on_request(
        "/image.iso", lambda n: os.kill(os.getpid(), signum) if n == 3 else None
    )


@pytest.mark.parametrize(
    "signum, code",
    [(signal.SIGINT, 130), (signal.SIGTERM, 143)],
    ids=["SIGINT", "SIGTERM"],
)
def test_signal_during_a_slow_download(slow, capsys, signum, code):
    server = slow[3]
    signal_on_third_chunk(server, signum)
    assert download(slow) == code
    captured = capsys.readouterr()
    assert captured.out == ""
    lines = [l for l in captured.err.splitlines() if l.startswith("chunkget: error: ")]
    assert len(lines) == 1
    # The two finished chunks are kept; the interrupted one is not trusted.
    assert saved_states(slow) == "CCPPP"


def test_the_download_can_be_resumed_after_a_signal(slow, capsys):
    server = slow[3]
    signal_on_third_chunk(server, signal.SIGINT)
    assert download(slow) == 130
    server.hooks.clear()
    server.delays.clear()
    server.requests.clear()
    capsys.readouterr()
    assert download(slow) == 0
    assert [r.range for r in server.requests] == [
        "bytes=100-149", "bytes=150-199", "bytes=200-249"
    ]
    assert slow[2].read_bytes() == CONTENT
    assert saved_states(slow) == "CCCCC"


def test_no_temporary_files_and_the_lock_is_released(slow, capsys):
    server = slow[3]
    signal_on_third_chunk(server, signal.SIGTERM)
    assert download(slow) == 143
    names = sorted(p.suffix for p in slow[1].iterdir())
    assert names == [".json", ".lock"]
    server.hooks.clear()
    server.delays.clear()
    assert download(slow) == 0  # the lock can be taken again


def test_handlers_are_restored_after_main(slow, capsys):
    before = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
    server = slow[3]
    server.delays.clear()
    assert download(slow) == 0
    assert (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)) == before


def test_handlers_are_restored_after_a_signal(slow, capsys):
    before = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
    signal_on_third_chunk(slow[3], signal.SIGINT)
    assert download(slow) == 130
    assert (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)) == before


def test_signal_while_waiting_between_retry_passes(slow, capsys, monkeypatch):
    server = slow[3]
    server.delays.clear()
    server.corrupt_range("/image.iso", 50, 60)

    def interrupted_sleep(seconds):
        os.kill(os.getpid(), signal.SIGINT)
        import time

        time.sleep(5)  # the handler raises before this ends

    monkeypatch.setattr("time.sleep", interrupted_sleep)
    assert download(slow, "--max-retries", "3") == 130
    assert saved_states(slow) == "CFCCC"


def test_signal_while_asking_a_question(slow, capsys, monkeypatch):
    import io

    class Stdin(io.StringIO):
        def isatty(self):
            return True

        def readline(self):
            os.kill(os.getpid(), signal.SIGINT)
            import time

            time.sleep(5)

    slow[2].write_bytes(b"precious")
    monkeypatch.setattr("sys.stdin", Stdin())
    assert download(slow) == 130
    assert slow[2].read_bytes() == b"precious"


def test_main_from_another_thread_does_not_install_handlers(slow, capsys):
    slow[3].delays.clear()
    result = []
    thread = threading.Thread(target=lambda: result.append(download(slow)))
    thread.start()
    thread.join()
    assert result == [0]
