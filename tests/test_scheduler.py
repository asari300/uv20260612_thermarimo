import pytest

import src.mod.scheduler as scheduler_mod
from src.mod.config import DeviceConfig, Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        api_key="K" * 45,
        login_id="USER0001",
        login_pass="pass",
        devices=[DeviceConfig(serial="SERIAL01", label="1号機")],
        data_root=tmp_path / "data",
    )


class StubScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(self, *args, **kwargs):
        self.jobs.append((args, kwargs))


def test_build_scheduler_has_four_cron_jobs(settings):
    scheduler = scheduler_mod.build_scheduler(settings)
    jobs = scheduler.get_jobs()
    assert len(jobs) == 4
    hours = sorted(int(str(job.trigger.fields[5])) for job in jobs)  # fields[5] = hour
    assert hours == [2, 8, 14, 20]
    assert all(job.coalesce for job in jobs)
    assert all(job.misfire_grace_time == 300 for job in jobs)


def test_collect_job_schedules_retry_on_failure(settings, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler_mod, "run_collection", boom)
    stub = StubScheduler()
    scheduler_mod.collect_job(settings, stub, retry=0)
    assert len(stub.jobs) == 1
    _args, kwargs = stub.jobs[0]
    assert kwargs["kwargs"] == {"retry": 1}


def test_collect_job_stops_at_max_retries(settings, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler_mod, "run_collection", boom)
    stub = StubScheduler()
    scheduler_mod.collect_job(settings, stub, retry=scheduler_mod.MAX_RETRIES)
    assert stub.jobs == []


def test_collect_job_no_retry_on_success(settings, monkeypatch):
    calls = []
    monkeypatch.setattr(
        scheduler_mod, "run_collection", lambda *a, **k: calls.append(a)
    )
    stub = StubScheduler()
    scheduler_mod.collect_job(settings, stub)
    assert len(calls) == 1
    assert stub.jobs == []
