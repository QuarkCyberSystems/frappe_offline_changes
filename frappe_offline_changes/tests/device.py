"""A device that works offline, reduced to what it exchanges with the site.

It reads records while connected, changes its own copies while disconnected, then sends what it changed and
asks what became of it. It speaks HTTP only and imports nothing of Frappe, so it is also the shortest
description of what an offline app has to do:

        device = Device("https://site.example", api_key, api_secret, device_id="tablet-1")
        todo = device.read("ToDo", name)            # connected
        device.change(todo, priority="High")        # offline: the copy changes, the change is kept
        device.sync()                               # connected again: the changes are sent
        device.outcomes()                           # {change_id: {"status": "Applied", ...}}
"""

import time
import uuid

import requests

SUBMIT = "frappe_offline_changes.api.changes.submit"
STATUS = "frappe_offline_changes.api.changes.status"


class Device:
	def __init__(self, url: str, api_key: str, api_secret: str, device_id: str, site: str | None = None):
		self.url = url.rstrip("/")
		self.device_id = device_id
		self.http = requests.Session()
		self.http.headers["Authorization"] = f"token {api_key}:{api_secret}"
		if site:
			# A bench serves several sites from one address and tells them apart by this header
			self.http.headers["Host"] = site
		self.pending: list[dict] = []
		self.sent: list[str] = []

	# Connected

	def call(self, endpoint: str, **arguments):
		response = self.http.post(f"{self.url}/api/method/{endpoint}", json=arguments, timeout=60)
		response.raise_for_status()
		return response.json().get("message")

	def read(self, doctype: str, name: str) -> dict:
		response = self.http.get(f"{self.url}/api/resource/{doctype}/{name}", timeout=60)
		response.raise_for_status()
		return response.json()["data"]

	def sync(self) -> dict:
		"""Send the changes kept since the last exchange, in the order they were made."""
		if not self.pending:
			return {}
		answer = self.call(SUBMIT, changes=self.pending, device_id=self.device_id)
		self.sent += [change["change_id"] for change in self.pending]
		self.last_batch, self.pending = self.pending, []
		return answer["changes"]

	def send_again(self) -> dict:
		"""The last batch once more, as after a connection lost before the answer arrived."""
		return self.call(SUBMIT, changes=self.last_batch, device_id=self.device_id)["changes"]

	def outcomes(self, wait: float = 30) -> dict:
		"""What became of the changes sent; waits until the site has processed them all."""
		deadline = time.monotonic() + wait
		while True:
			outcomes = self.call(STATUS, change_ids=self.sent) or {}
			done = len(outcomes) == len(self.sent) and all(
				o["status"] != "Received" for o in outcomes.values()
			)
			if done or time.monotonic() > deadline:
				return outcomes
			time.sleep(0.5)

	# Offline

	def change(self, record: dict, **fields) -> str:
		"""Change the device's copy of a record; each field is sent with the value the copy held."""
		change = {
			**self._change("Update", record["doctype"], record["name"]),
			"fields": {
				fieldname: {"from": record.get(fieldname), "to": value} for fieldname, value in fields.items()
			},
		}
		if not record.get("__created_offline"):
			change["base_modified"] = record["modified"]
		record.update(fields)
		return self._keep(change)

	def create(self, doctype: str, **values) -> dict:
		"""A record made on the device, under a name the device gives it until the site has its own."""
		record = {"doctype": doctype, "name": str(uuid.uuid4()), "__created_offline": True, **values}
		self._keep({**self._change("Create", doctype, record["name"]), "values": values})
		return record

	def delete(self, record: dict) -> str:
		return self._keep(
			{**self._change("Delete", record["doctype"], record["name"]), "base_modified": record["modified"]}
		)

	def _change(self, operation: str, doctype: str, name: str) -> dict:
		return {
			"change_id": str(uuid.uuid4()),
			"operation": operation,
			"doctype": doctype,
			"name": name,
			"captured_on": time.strftime("%Y-%m-%d %H:%M:%S"),
		}

	def _keep(self, change: dict) -> str:
		self.pending.append(change)
		return change["change_id"]
