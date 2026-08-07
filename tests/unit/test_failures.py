from ai_council.failures import FailureKind, classify_failure


def _c(stdout="", stderr="", exit_code=1, timed_out=False):
    return classify_failure(stdout, stderr, exit_code=exit_code, timed_out=timed_out)


def test_connection_drop_is_transient():
    d = _c(stdout="API Error: Connection closed mid-response. The response above may be incomplete.")
    assert d.kind == FailureKind.TRANSIENT
    assert d.retry_transiently and not d.fail_fast


def test_overloaded_and_5xx_are_transient():
    assert _c(stderr="overloaded_error: Overloaded").kind == FailureKind.TRANSIENT
    assert _c(stderr="Internal server error").kind == FailureKind.TRANSIENT
    assert _c(stderr="ECONNRESET while streaming").kind == FailureKind.TRANSIENT


def test_usage_limit_fails_fast_with_reset_info():
    d = _c(stdout="You've hit your session limit · resets 3:10pm (America/Santo_Domingo)")
    assert d.kind == FailureKind.USAGE_LIMIT
    assert d.fail_fast
    assert "resets 3:10pm" in d.detail


def test_rate_limit_is_usage_limit():
    assert _c(stderr="429 Too Many Requests").kind == FailureKind.USAGE_LIMIT


def test_auth_fails_fast():
    d = _c(stdout="Failed to authenticate: OAuth session expired and could not be refreshed")
    assert d.kind == FailureKind.AUTH
    assert d.fail_fast


def test_timeout_kind():
    d = _c(timed_out=True)
    assert d.kind == FailureKind.TIMEOUT
    assert not d.retry_transiently and not d.fail_fast


def test_unknown_is_agent_failure():
    d = _c(stdout="something exploded for reasons", exit_code=7)
    assert d.kind == FailureKind.AGENT
    assert "code 7" in d.detail
