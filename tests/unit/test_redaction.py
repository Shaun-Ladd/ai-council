from ai_council.redaction import REDACTED, redact, sensitive_env_values


def test_api_key_patterns():
    text = "key sk-ant-abc123def456ghi789 and ghp_ABCDEFGHIJKLMNOPQRSTUV123456"
    out = redact(text, environ={})
    assert "sk-ant-" not in out
    assert "ghp_" not in out
    assert out.count(REDACTED) == 2


def test_key_value_assignments_keep_key():
    out = redact("export MY_API_KEY=supersecretvalue", environ={})
    assert "MY_API_KEY=" in out
    assert "supersecretvalue" not in out


def test_private_key_block():
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----"
    assert redact(text, environ={}) == REDACTED


def test_env_value_redaction():
    env = {"GITHUB_TOKEN": "tok-not-a-pattern-value", "SAFE": "visible"}
    out = redact("output tok-not-a-pattern-value and visible", environ=env)
    assert "tok-not-a-pattern-value" not in out
    assert "visible" in out


def test_sensitive_env_selection():
    env = {"MY_SECRET": "abcdefgh", "PATH": "/usr/bin", "PW": "x"}
    values = sensitive_env_values(env)
    assert "abcdefgh" in values
    assert "/usr/bin" not in values  # PATH not sensitive
    assert "x" not in values         # too short


def test_extra_values():
    out = redact("the password is hunter2hunter2", extra_values=["hunter2hunter2"], environ={})
    assert "hunter2hunter2" not in out
