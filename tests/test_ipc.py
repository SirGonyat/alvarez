"""
Unit tests for atomic shared memory IPC buffer.
"""

import os
from alvarez.core.ipc import SharedBuffer


def test_shared_buffer_write_and_read():
    test_file = "test_alvarez_shm.txt"
    buffer = SharedBuffer(test_file, size=1024)

    test_message = "🎵 Testing Audio Equalizer Line [ ▃▅▆▇] L:50% R:55%"
    success = buffer.write(test_message)
    assert success is True

    read_back = buffer.read()
    assert read_back == test_message

    buffer.close()
    # Cleanup test artifact
    for base in ("/dev/shm", "/tmp"):
        path = os.path.join(base, test_file)
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
