"""LO-08 (Part 2K-4): the PMS outbox runs on its own RQ queue, never in a job the 5-minute group waits behind.

The 5-minute cron entry ``outbox_every_5_minutes`` ran ``outbox.deliver_pending`` inline in the scheduler's job, on
the default queue. With one worker, a slow PMS (a 120 s budget plus one 30 s call) held the holds, payments and links
of ``every_5_minutes`` behind it for up to about 150 s. The entry now only queues the delivery on the ``long`` queue
under one job id (a delivery still queued or running is not queued again), and the local deploy runs a worker for
that queue next to the one for ``short,default``.
"""

import pathlib
import re
import unittest
from unittest import mock

import frappe

from kamra.tex import scheduler

ROOT = pathlib.Path(__file__).resolve().parents[4]
WORKER = re.compile(r"^(?:echo \")?(\w+): .*?\bbench worker\b(?: --queue (\S+))?")


def workers(lines) -> dict[str, set[str] | None]:
	"""{process name: the queues its ``bench worker`` listens on (None: every queue)} of Procfile lines."""
	out = {}
	for line in lines:
		m = WORKER.match(line.strip())
		if m:
			out[m.group(1)] = set(m.group(2).split(",")) if m.group(2) else None
	return out


class TestPmsOutboxQueue(unittest.TestCase):
	def test_the_cron_entry_only_queues_the_delivery_on_its_own_queue(self):
		with mock.patch.object(scheduler, "_run") as run, mock.patch.object(frappe, "enqueue") as enqueue:
			scheduler.outbox_every_5_minutes()
		run.assert_not_called()
		enqueue.assert_called_once()
		(method,), kw = enqueue.call_args
		self.assertEqual(method, "kamra.tex.scheduler.deliver_outbox")
		self.assertEqual((kw["queue"], kw["job_id"], kw["deduplicate"]), ("long", "tex_pms_outbox", True))
		# its own time limit: the delivery's budget (120 s) and one PMS call (30 s) fit, a hung call is ended
		self.assertGreaterEqual(kw["timeout"], 150)
		self.assertLessEqual(kw["timeout"], 300)

	def test_the_queued_delivery_runs_each_outbox_job_isolated(self):
		with mock.patch.object(scheduler, "_run") as run:
			scheduler.deliver_outbox()
		self.assertEqual([c.args[0] for c in run.call_args_list], ["kamra.tex.connect.outbox.deliver_pending"])

	def test_the_local_deploy_runs_a_worker_for_the_long_queue(self):
		"""The Procfile and the one ``setup-local.sh`` writes: a worker for ``long`` only, the others never on it
		(a worker of every queue would take the delivery and hold the group behind it again)."""
		procfile = (ROOT / "deploy/tex-local/Procfile").read_text().splitlines()
		script = [line for line in (ROOT / "deploy/tex-local/setup-local.sh").read_text().splitlines()
		          if line.strip().startswith('echo "') and "bench worker" in line]
		for name, lines in (("Procfile", procfile), ("setup-local.sh", script)):
			found = workers(lines)
			self.assertIn({"long"}, found.values(), name)
			for queues in found.values():
				self.assertIsNotNone(queues, f"{name}: a worker of every queue")
				if queues != {"long"}:
					self.assertEqual(queues, {"short", "default"}, name)


class _Worker:
	def __init__(self, *queues):
		self.queues = [f"bench:{q}" for q in queues]

	def queue_names(self):
		return self.queues


class TestQueueProbe(unittest.TestCase):
	"""2K-4 review round 1 (LO-08): the status page's probe of the RQ queues, Redis stubbed."""

	def probe(self, *workers):
		from kamra.tex.ops import status

		class Conn:
			def ping(self):
				return True

		def get_redis_conn():
			return Conn()

		class Queue:
			def __init__(self, name, connection):
				self.count = 0

		with mock.patch("frappe.utils.background_jobs.get_redis_conn", get_redis_conn), \
				mock.patch("frappe.utils.background_jobs.get_queue_list", return_value=["default", "short", "long"]), \
				mock.patch("frappe.utils.background_jobs.generate_qname", lambda q: f"bench:{q}"), \
				mock.patch("rq.Queue", Queue), mock.patch("rq.Worker.all", return_value=list(workers)):
			return status.queue_probe()

	def test_each_queue_tex_queues_jobs_on_is_named_when_no_worker_listens_on_it(self):
		from kamra.tex.ops import status

		# guest changes and refusal audits are queued on short, the cron entries on default, the PMS outbox on long
		self.assertEqual(status.TEX_QUEUES, ("short", "default", "long"))
		self.assertEqual(self.probe(_Worker("short", "default"), _Worker("long"))["unserved"], [])
		self.assertEqual(self.probe(_Worker("short", "default", "long"))["unserved"], [])
		self.assertEqual(self.probe(_Worker("long"))["unserved"], ["short", "default"])
		self.assertEqual(self.probe(_Worker("short", "default")),
		                 {"reachable": True, "workers": 1, "backlog": 0, "unserved": ["long"]})

	def test_a_delivery_waiting_in_its_queue_is_counted_in_minutes(self):
		from datetime import UTC, datetime, timedelta

		from rq.job import JobStatus

		from kamra.tex.ops import status

		def job(state, minutes):
			j = mock.Mock(enqueued_at=datetime.now(UTC) - timedelta(minutes=minutes, seconds=30))
			j.get_status.return_value = state
			return j

		from rq.exceptions import NoSuchJobError

		key = "kamra.tex.scheduler.outbox_every_5_minutes"
		conn = mock.Mock()
		for found, waiting in ((job(JobStatus.QUEUED, 25), {key: 25}), (job(JobStatus.STARTED, 25), {}),
		                       (job(JobStatus.FINISHED, 25), {}), (NoSuchJobError("gone"), {})):
			fetch = {"side_effect": found} if isinstance(found, Exception) else {"return_value": found}
			with mock.patch.object(status, "_redis_once", return_value=conn), \
					mock.patch("frappe.utils.background_jobs.create_job_id", lambda j: f"site||{j}"), \
					mock.patch("rq.job.Job.fetch", **fetch) as get:
				self.assertEqual(status.waiting_jobs(), waiting)
			get.assert_called_once_with("site||tex_pms_outbox", connection=conn)
		# Redis unreachable: one attempt (never Frappe's five), never raises: the workers check says it
		with mock.patch.object(status, "_redis_once", side_effect=ConnectionError("no redis")):
			self.assertEqual(status.waiting_jobs(), {})


if __name__ == "__main__":
	unittest.main()
