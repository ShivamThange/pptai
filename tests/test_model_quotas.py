"""Per-model RPM/TPM/RPD windows: overlapping edges, rolling days, and reservation settlement."""
import pytest
from fastapi.testclient import TestClient

import infrastructure.llm.llm_client as gateway
from api.app import create_app
from config.model_quotas import GEMINI_QUOTAS, ModelQuota, declared_models, normalize_model, parse_env_quotas, quota_for
from config.settings import get_multi_agent_settings, resolve_environment
from infrastructure.llm.context_budget import ContextBudgetError
from infrastructure.llm.llm_client import LLMRequestError, QuotaWindow, Reservation, RpmLimiter
from workers.local import LocalWorker, safe_error
from test_service_jobs import queued


class Clock:
    def __init__(self):
        self.now = 0.0
        self.waits = []

    def __call__(self):
        return self.now

    def forward(self, seconds):
        """Test bookkeeping: time passing between calls is not a limiter wait."""
        self.now += seconds

    def advance(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    instance = Clock()

    def wait_once(delay, *, deadline, clock, sleep, cancel):
        # Splitting a wait into 0.1s slices would hide whether the limiter woke into a
        # still-saturated window; recording one delay keeps the assertion about window math.
        clock.advance(delay)

    monkeypatch.setattr(gateway, "_wait", wait_once)
    return instance


def quota(rpm=10, tpm=10_000, rpd=1_000):
    return ModelQuota("fixture-model", rpm=rpm, tpm=tpm, rpd=rpd)


def make_limiter(clock, models=None, *, max_calls=10, max_tokens=None):
    return RpmLimiter(max_calls, clock=clock, max_tokens=max_tokens, model_quotas=models or {})


def test_a_weight_larger_than_the_capacity_can_never_be_admitted():
    assert QuotaWindow("TPM", 100, 60.0, unit="tokens").admit_at(0.0, 101) is None


def test_an_event_leaves_its_window_exactly_one_period_after_it_started():
    window = QuotaWindow("RPM", 1, 60.0)
    window.commit(0.0, 1)
    assert window.admit_at(59.5, 1) == 60.0
    assert window.admit_at(60.0, 1) == 60.0


def test_admit_waits_for_enough_weight_to_expire_not_just_for_the_first_edge():
    window = QuotaWindow("TPM", 100, 60.0, unit="tokens")
    for started_at, weight in [(0.0, 2), (10.0, 2), (20.0, 60)]:
        window.commit(started_at, weight)
    # The first edge alone frees 2 tokens; 40 are needed, so the instant that admits
    # this call is the second edge at 70, not 60.
    assert window.admit_at(30.0, 40) == 70.0


def test_staggered_window_edges_resolve_with_a_single_wait(clock):
    limiter = make_limiter(clock, {"model-a": quota(rpm=2, tpm=100, rpd=1_000)})
    limiter.acquire(model="model-a", tokens=10)
    clock.forward(40)
    limiter.acquire(model="model-a", tokens=80)
    clock.forward(10)
    limiter.acquire(model="model-a", tokens=50)
    # RPM clears at 60, TPM not before 100: waking at 60 would re-check a full token
    # window and spin, so the limiter sleeps straight to the latest edge.
    assert clock.waits == [50.0]
    assert clock.now == 100.0


def test_coincident_edges_clear_in_one_step(clock):
    limiter = make_limiter(clock, {"model-a": quota(rpm=1, tpm=100, rpd=1_000)})
    limiter.acquire(model="model-a", tokens=100)
    limiter.acquire(model="model-a", tokens=1)
    assert clock.waits == [60.0]
    assert clock.now == 60.0


def test_one_models_capacity_is_not_consumed_by_another(clock):
    limiter = make_limiter(clock, {"model-a": quota(rpm=1), "model-b": quota(rpm=3)})
    limiter.acquire(model="model-a")
    for _ in range(3):
        limiter.acquire(model="model-b")
    assert clock.waits == []
    limiter.acquire(model="model-b")
    assert clock.waits == [60.0]


def test_the_process_wide_cap_still_guards_every_model(clock):
    limiter = make_limiter(clock, {"model-a": quota(), "model-b": quota()}, max_calls=1)
    limiter.acquire(model="model-a")
    limiter.acquire(model="model-b")
    assert clock.waits == [60.0]


def test_an_undeclared_model_only_gets_the_process_wide_caps(clock):
    limiter = make_limiter(clock, {"model-a": quota(rpm=1, tpm=10, rpd=1)})
    for _ in range(10):
        limiter.acquire(model="not-declared-anywhere")
    assert limiter._model_windows("not-declared-anywhere") == []
    assert clock.waits == []


def test_the_same_model_under_two_id_spellings_shares_one_window(clock):
    limiter = make_limiter(clock, {"gemini-3.1-flash-lite": quota(rpm=1)})
    limiter.acquire(model="models/gemini-3.1-flash-lite")
    limiter.acquire(model="Gemini-3.1-Flash-Lite")
    assert clock.waits == [60.0]


def test_a_reservation_settles_to_real_usage_and_releases_the_rest(clock):
    limiter = make_limiter(clock, {"model-a": quota(tpm=100)})
    reserved = limiter.acquire(model="model-a", tokens=90)
    assert isinstance(reserved, Reservation)
    reserved.settle(5, 5)
    clock.forward(10)
    limiter.acquire(model="model-a", tokens=90)
    assert clock.waits == []


def test_settling_above_capacity_clamps_instead_of_wedging_the_window(clock):
    limiter = make_limiter(clock, {"model-a": quota(tpm=100)})
    limiter.acquire(model="model-a", tokens=50).settle(1_000, 1_000)
    clock.forward(10)
    limiter.acquire(model="model-a", tokens=50)
    assert clock.waits == [50.0]


def test_an_unsettled_reservation_holds_the_whole_estimate(clock):
    limiter = make_limiter(clock, {"model-a": quota(tpm=100)})
    limiter.acquire(model="model-a", tokens=90)
    clock.forward(10)
    limiter.acquire(model="model-a", tokens=90)
    assert clock.waits == [50.0]


@pytest.mark.parametrize("usage", [(None, 5), (5, None)])
def test_a_partial_usage_report_is_never_trusted_as_a_refund(clock, usage):
    limiter = make_limiter(clock, {"model-a": quota(tpm=100)})
    reserved = limiter.acquire(model="model-a", tokens=90)
    reserved.settle(*usage)
    clock.forward(10)
    limiter.acquire(model="model-a", tokens=90)
    assert clock.waits == [50.0]


def test_a_call_beyond_the_model_token_quota_fails_before_it_waits(clock):
    limiter = make_limiter(clock, {"model-a": quota(tpm=100)})
    with pytest.raises(ContextBudgetError) as error:
        limiter.acquire(model="model-a", tokens=101)
    assert error.value.code == "MODEL_QUOTA_EXCEEDED"
    assert (error.value.required, error.value.available) == (101, 100)
    assert clock.waits == []


def test_the_process_token_cap_is_checked_before_any_model_window(clock):
    limiter = make_limiter(clock, {"model-a": quota(tpm=250_000)}, max_tokens=100)
    with pytest.raises(ContextBudgetError, match="RUN_CONTEXT_BUDGET_EXHAUSTED"):
        limiter.acquire(model="model-a", tokens=101)


def test_an_exhausted_day_raises_a_quota_error_when_capacity_outlives_the_deadline(clock):
    limiter = make_limiter(clock, {"model-a": quota(rpd=2)})
    for _ in range(2):
        limiter.acquire(model="model-a")
    with pytest.raises(LLMRequestError) as error:
        limiter.acquire(model="model-a", deadline=3_600.0)
    assert error.value.error_class == "quota"
    assert "model-a RPD" in str(error.value)
    assert error.value.retry_after == pytest.approx(86_400.0)
    assert clock.waits == []


def test_an_exhausted_day_without_a_deadline_waits_for_the_rolling_day(clock):
    limiter = make_limiter(clock, {"model-a": quota(rpd=2)})
    for _ in range(2):
        limiter.acquire(model="model-a")
    limiter.acquire(model="model-a")
    assert clock.waits == [86_400.0]


def test_a_process_wide_breach_is_reported_as_a_deadline_not_a_model_quota(clock):
    # Only a declared model limit can be quoted back as "this model is exhausted"; a
    # shared-cap breach past the call deadline stays a plain deadline failure.
    limiter = make_limiter(clock, max_calls=1)
    limiter.acquire()
    with pytest.raises(LLMRequestError) as error:
        limiter.acquire(deadline=10.0)
    assert error.value.error_class == "deadline"
    assert "quota" not in str(error.value)


def test_quota_failures_reach_the_worker_as_actionable_errors():
    quota_error = safe_error(LLMRequestError("model-a RPD limit of 20 per 86400s is exhausted",
                                             error_class="quota", retry_after=86_400), "slide_repair")
    assert quota_error["code"] == "LLM_QUOTA" and quota_error["stage"] == "slide_repair"
    assert "model" in quota_error["message"] and "resume" in quota_error["message"]
    oversized = safe_error(ContextBudgetError("MODEL_QUOTA_EXCEEDED", stage="build", required=101, available=100),
                           "slide_composition")
    assert oversized["code"] == "MODEL_QUOTA_EXCEEDED"
    assert (oversized["required"], oversized["available"]) == (101, 100)
    assert "tokens-per-minute" in oversized["message"]


@pytest.mark.parametrize("spelling", ["gemini-3.6-flash", "models/gemini-3.6-flash",
                                      "publishers/google/models/gemini-3.6-flash",
                                      "Gemini-3.6-Flash", "gemini-3.6-flash@v1", "gemini-3.6-flash:online",
                                      "gemini-3.6-flash-latest"])
def test_id_spellings_resolve_to_one_declared_quota(spelling):
    assert normalize_model(spelling) == "gemini-3.6-flash"
    assert quota_for("gemini", spelling) == GEMINI_QUOTAS["gemini-3.6-flash"]


def test_an_unlisted_model_has_no_quota_and_an_empty_provider_table_declares_nothing():
    assert quota_for("gemini", "gemini-9-ultra") is None
    assert declared_models("openrouter", {}) == {}
    assert declared_models("unknown-provider", {}) == {}


def test_declared_gemini_quotas_match_the_provider_page():
    assert {model: (quota.rpm, quota.tpm, quota.rpd) for model, quota in GEMINI_QUOTAS.items()} == {
        "gemini-3-flash": (5, 250_000, 20), "gemini-3.6-flash": (5, 250_000, 20),
        "gemini-3.8-flash": (5, 250_000, 20), "gemini-3.1-flash-lite": (15, 250_000, 500),
        "gemini-3.5-flash-lite": (15, 250_000, 500)}


def test_environment_declarations_extend_and_override_the_built_in_table():
    models = declared_models("gemini", {"LLM_MODEL_QUOTAS": "models/gemini-3-flash:9:900:90,gemini-9-ultra:1:2:3"})
    assert models["gemini-3-flash"] == ModelQuota("gemini-3-flash", rpm=9, tpm=900, rpd=90)
    assert models["gemini-9-ultra"].rpd == 3
    assert models["gemini-3.6-flash"] == GEMINI_QUOTAS["gemini-3.6-flash"]


@pytest.mark.parametrize("raw", ["gemini-3-flash:5", "gemini-3-flash:five:1:1", "gemini-3-flash:0:1:1",
                                 "gemini-3-flash:-1:100:100", "gemini-3-flash:1:1:0"])
def test_a_malformed_environment_quota_is_a_configuration_error(raw):
    with pytest.raises(ValueError):
        parse_env_quotas(raw)


def test_worker_limiter_enforces_the_table_it_advertises(tmp_path):
    from config.service_settings import ServiceSettings
    from infrastructure.persistence.jobs import JobStore
    settings = ServiceSettings(root=tmp_path / "service", poll_interval=.01)
    provider = get_multi_agent_settings({"LLM_PROVIDER": "gemini"})
    worker = LocalWorker(settings, store=JobStore(settings.database), provider_settings=provider)
    assert worker.limiter.model_quotas == declared_models("gemini", resolve_environment())
    assert set(worker.limiter.model_quotas) == set(GEMINI_QUOTAS)


@pytest.fixture
def api(queued):
    settings, store, worker, callers = queued
    provider = get_multi_agent_settings({"LLM_PROVIDER": "gemini"})
    with TestClient(create_app(settings, provider_settings=provider)) as client:
        yield client, settings, store, worker, callers


def test_config_advertises_each_model_with_the_limits_it_enforces(api):
    client, *_ = api
    config = client.get("/api/config").json()
    assert config["provider"] == "gemini" and config["model"] == "gemini-3.1-flash-lite"
    by_model = {entry["model"]: entry for entry in config["models"]}
    assert set(by_model) == set(GEMINI_QUOTAS)
    assert by_model["gemini-3-flash"] == {"model": "gemini-3-flash", "label": "Gemini 3 Flash", "rpm": 5,
                                         "tpm": 250_000, "rpd": 20, "declared": True, "current": False}
    assert [entry["current"] for entry in config["models"]] == [True] + [False] * (len(config["models"]) - 1)


def test_an_undeclared_provider_default_stays_selectable(queued):
    settings, store, worker, callers = queued
    provider = get_multi_agent_settings({"LLM_PROVIDER": "gemini", "GEMINI_MODEL": "gemini-9-ultra"})
    with TestClient(create_app(settings, provider_settings=provider)) as client:
        config = client.get("/api/config").json()
    undeclared = [entry for entry in config["models"] if not entry["declared"]]
    assert undeclared == [{"model": "gemini-9-ultra", "label": "gemini-9-ultra",
                           "rpm": provider.max_calls_per_minute, "tpm": provider.max_tokens_per_minute,
                           "rpd": None, "declared": False, "current": True}]
    assert len(config["models"]) == len(GEMINI_QUOTAS) + 1


def test_a_selection_pins_the_model_and_the_tiered_routing_together(api):
    client, _, store, *_ = api
    deck = client.post("/api/decks", json={"document_id": "doc", "model": "gemini-3-flash"}).json()
    job = store.get(deck["job_id"])
    assert job.request["provider_config"]["model"] == job.request["provider_config"]["fast_model"] == "gemini-3-flash"
    assert "model" not in {key for key in job.request if key != "provider_config"}
    published = client.get(f"/api/jobs/{deck['job_id']}").json()
    assert published["model"] == published["fast_model"] == "gemini-3-flash"
    assert client.get("/api/jobs").json()[0]["model"] == "gemini-3-flash"
    resumed = client.post(f"/api/decks/{deck['deck_id']}/generate", json={"resume": True}).json()
    # A follow-up with no explicit choice falls back to the server default, not to the
    # model the previous job happened to run on.
    assert store.get(resumed["job_id"]).request["provider_config"]["model"] == "gemini-3.1-flash-lite"


def test_a_chosen_model_reaches_the_gateway_and_stops_at_the_pipeline_boundary(api, monkeypatch):
    client, settings, store, worker, callers = api
    seen = {}

    def generate_deck(source, parse_root, options, *, context, caller, **kwargs):
        seen['options'] = set(vars(options))
        seen['provider'] = context.provider_settings
        raise RuntimeError("Injected stop at the pipeline boundary")

    monkeypatch.setattr("pipeline.service.generate_deck", generate_deck)
    deck = client.post("/api/decks", json={"document_id": "doc", "model": "gemini-3-flash"}).json()
    with worker.lifetime():
        worker.process_next()
    assert store.get(deck["job_id"]).status == "failed"
    assert seen['provider'].model == seen['provider'].fast_model == "gemini-3-flash"
    # The gateway takes its model from provider configuration; the scope/retry options
    # must not grow a second copy that a submission can contradict.
    assert "model" not in seen['options']


def test_a_model_the_server_does_not_offer_is_rejected(api):
    client, _, store, *_ = api
    for body in ({"document_id": "doc", "model": "gpt-4o"}, {"document_id": "doc", "model": "  "}):
        response = client.post("/api/decks", json=body)
        assert response.status_code == 422
        if body["model"] == "gpt-4o":
            assert response.json()["detail"]["code"] == "UNKNOWN_MODEL"
            assert "gemini-3.6-flash" in response.json()["detail"]["models"]
    assert not store.recent_jobs(50)
