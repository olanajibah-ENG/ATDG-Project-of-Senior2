import socket, os

def test_network_is_off():
    socket.create_connection(("example.com", 80), timeout=3)

def test_source_is_read_only():
    with open("/workspace/src/hack.py", "w") as f:
        f.write("x = 1")

def test_who_am_i():
    assert os.getuid() == 10001

def test_no_secret_in_env():
    ours = ("OPENROUTER", "SECRET_KEY", "JWT", "MONGO", "REDIS", "DJANGO", "CELERY", "PASSWORD", "TOKEN")
    leaked = [k for k in os.environ if any(word in k for word in ours)]
    assert leaked == [], leaked

def test_network_is_off_even_by_ip():
    socket.create_connection(("1.1.1.1", 80), timeout=3)

def test_forever():
    while True:
        pass