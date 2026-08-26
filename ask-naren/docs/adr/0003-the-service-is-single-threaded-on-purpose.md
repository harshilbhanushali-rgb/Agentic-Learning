# Ask Naren's service is stdlib `http.server`, single-threaded, on purpose

Ask Naren needs one HTTP endpoint that takes a CSM's free-text situation and returns a grounded answer or a decline, plus a readiness check. Its request path embeds the incoming situation through `preprocessing/embedder.py`, which writes through a disk cache in `shared/embed_cache.py`.

We decided to serve it with the standard library's `http.server` rather than a web framework, and to serve requests **one at a time** rather than with `ThreadingHTTPServer`.

Two independent reasons, one of them a hard constraint rather than a preference:

**The cache connection is thread-bound.** `shared/embed_cache.py` opens its SQLite connection with a bare `sqlite3.connect(path)` — no `check_same_thread=False`. A second request thread touching that connection raises outright. Serialising requests is the honest fix for an internal tool whose requests take a few seconds each; making that cache thread-safe, or pinning embedding to a dedicated worker thread, is a change to `shared/` that would affect every Brain consumer and is not something a CSM-facing endpoint should be the reason for.

**There is nothing here a framework would do.** One JSON POST and one health GET. Adding `fastapi` and `uvicorn` to Brain's venv to route two paths is cost without benefit.

The consequence to know, and it is real: `/health` queues behind an in-flight generation, and total throughput is one question at a time. For the current audience that is acceptable. If Ask Naren ever needs concurrency, the blocker to remove first is the embed cache's thread affinity, not the choice of server.

## A defect this design caused, found by test and fixed

Keep-alive on a serial server is a self-inflicted outage. With HTTP/1.1 defaults, the accept loop blocks in `handle_one_request` waiting for another request on an idle socket, so **one client that leaves a connection open makes every subsequent caller time out** — measured, not theorised. The Next.js proxy in issue #3 would have hit this on its second request.

Every response therefore sets `Connection: close` and `self.close_connection = True`. Do not "optimise" that back to keep-alive without first removing the single-threading constraint above.
