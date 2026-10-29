"""ai-review-gate.py が使う GitHub REST API の最小クライアント (標準ライブラリのみ)。"""

import json
import urllib.error
import urllib.request


class GitHubClient:
	def __init__(self, token, api_url):
		self.token = token
		self.api_url = api_url.rstrip("/")

	def request(self, method, path, payload=None):
		url = f"{self.api_url}{path}"
		data = json.dumps(payload).encode("utf-8") if payload is not None else None
		request = urllib.request.Request(
			url,
			data=data,
			method=method,
			headers={
				"Accept": "application/vnd.github+json",
				"Authorization": f"Bearer {self.token}",
				"User-Agent": "ai-review-gate",
				"X-GitHub-Api-Version": "2022-11-28",
				"Content-Type": "application/json",
			},
		)
		try:
			with urllib.request.urlopen(request, timeout=30) as response:
				body = response.read()
				return json.loads(body) if body else None
		except urllib.error.HTTPError as error:
			body = error.read().decode("utf-8", errors="replace")
			raise RuntimeError(f"GitHub API {error.code}: {body}") from error
		except urllib.error.URLError as error:
			raise RuntimeError(f"GitHub API connection failed: {error.reason}") from error

	def get(self, path):
		return self.request("GET", path)

	def get_paginated(self, path):
		items = []
		page = 1
		separator = "&" if "?" in path else "?"
		while True:
			batch = self.get(f"{path}{separator}per_page=100&page={page}")
			if not isinstance(batch, list):
				raise RuntimeError(f"Expected a list from GitHub API: {path}")
			items.extend(batch)
			if len(batch) < 100:
				return items
			page += 1

	def publish_status(self, repo, sha, context, state, description, target_url):
		payload = {"state": state, "context": context, "description": description[:140]}
		if target_url:
			payload["target_url"] = target_url
		return self.request("POST", f"/repos/{repo}/statuses/{sha}", payload)
