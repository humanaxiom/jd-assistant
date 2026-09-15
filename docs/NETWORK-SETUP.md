# JD Bank — network setup guide

**Audience: the network / infrastructure administrator standing up a JD Bank box.**
Everything below is network-facing: addresses, ports, DNS, TLS, firewall, and the one
application setting that *must* match the network design or sign-in breaks. It does not
cover installing the app — that is [`deploy/README.md`](../deploy/README.md) — or using
it, which is [`OPERATOR-GUIDE.md`](OPERATOR-GUIDE.md).

---

## 1. The one thing to read before touching anything

**Every URL a user can reach JD Bank on must be listed, exactly, in
`ALLOWED_SERVICE_ORIGINS`.** Not "the hostname" — the full origin: **scheme + host +
port**, all three.

JD Bank authenticates against SFU CAS. CAS is told a "service" URL when a login starts
and must be told the byte-identical URL when the ticket is validated, so the app has to
decide *one* origin to send each user back to. It reads the origin the browser actually
used (`X-Forwarded-Host`, else `Host`) and returns it **only if it is on the allowlist**.
Anything else falls back to `CAS_SERVICE_BASE_URL`.

That fallback is the failure mode you will hit, and it does not look like a
configuration error. The user signs in at CAS successfully, then lands on
`ERR_CONNECTION_TIMED_OUT` at a *different* hostname, with a valid ticket in the URL bar.
Nothing appears in the app log, because the browser never got back to the app.

These are all **different origins** and each needs its own entry:

| reached as | origin to list |
|---|---|
| `https://jdbank.its.sfu.ca` | `https://jdbank.its.sfu.ca` |
| `https://jdbank.its.sfu.ca:8443` | `https://jdbank.its.sfu.ca:8443` |
| `http://jdbank.its.sfu.ca` | a *different* origin from the https one |
| `https://jdbank` (short name) | `https://jdbank` |
| `https://10.20.30.40` (bare IP) | `https://10.20.30.40` |

A short hostname is not the FQDN. `https://` is not `http://`. Port 443 spelled
explicitly is not port 443 omitted. Each variant users might type, or that a load
balancer might present, is its own entry.

**Why it is an allowlist and not just "trust the Host header":** the header is supplied
by the client. Without the list, anyone could set it and have an authenticated user —
carrying a live CAS ticket — delivered to a host of their choosing. The list is the
security control; the header read is not. See
[`core/src/api/service_origin.py`](../core/src/api/service_origin.py).

---

## 2. Inbound — what to open

Only **one** port should be reachable by users.

| port | service | exposure |
|---:|---|---|
| **25800** | HTTP API + web UI | the only port users need; behind TLS in production |
| 25432 | PostgreSQL | **localhost only** — never routed |
| 25474 / 25687 | Neo4j HTTP / Bolt | **localhost only** — never routed |
| 25379 | Redis | **localhost only** — never routed |

The non-default port numbers are deliberate: the box runs several Docker projects and
the standard ports collide. In `docker-compose.prod.yml` the data stores are bound to
`127.0.0.1`, and the API publishes to `${JD_API_BIND:-127.0.0.1}:${JD_API_PORT:-25800}` —
i.e. **loopback by default, on the assumption a reverse proxy on the same box terminates
TLS**. Set `JD_API_BIND=0.0.0.0` only if something else is doing TLS in front.

---

## 3. Outbound — what the box must reach

| destination | port | why | blocked ⇒ |
|---|---:|---|---|
| `cas.sfu.ca` | 443 | CAS ticket validation (server-to-server) | nobody can sign in |
| the Ollama host (`aria-gb10-2` by default) | 11434 | embeddings / LLM | ingest, search and compose degrade |
| DNS + NTP | 53 / 123 | name resolution; CAS is time-sensitive | intermittent auth failures |

**No other egress is required, and no LLM traffic may leave SFU-controlled
infrastructure** — the app enforces this itself via `ALLOWED_INFERENCE_HOSTS` and refuses
to start pointed anywhere else. If the Ollama host moves, that list is updated
deliberately, as a reviewed change.

---

## 4. DNS and TLS

- **One canonical FQDN**, A/AAAA to the box (or to the load balancer in front of it).
- **TLS is mandatory in production.** The app refuses to start when `ENVIRONMENT=production`
  and `CAS_SERVICE_BASE_URL` or any `ALLOWED_SERVICE_ORIGINS` entry is plain `http`, is
  `localhost`/loopback, or is still the shipped dev default. This is a hard refusal at
  startup, not a warning: over http the CAS ticket travels in clear and the `secure`
  session cookie is never sent, so login cannot complete anyway.
- **The certificate must match every hostname users type.** If both the FQDN and a short
  name are in use, the cert needs both — and both need allowlist entries.
- If users will reach the box by more than one name (a vanity CNAME, a legacy name),
  either put every name on the cert *and* the allowlist, or redirect the extras at the
  proxy to the canonical name. Redirecting is cleaner.

---

## 5. Reverse proxy / load balancer

If anything sits in front of the app, it must pass the **original** origin:

```
X-Forwarded-Host:  jdbank.its.sfu.ca          # what the user typed, including a non-443 port
X-Forwarded-Proto: https
```

Both are read, both are subject to the same allowlist, and **`X-Forwarded-Proto` does not
promote an http entry to https** — the scheme is part of the match. Measured on the
running app:

```
X-Forwarded-Host: 192.168.1.80:25800  Proto: http   -> http://192.168.1.80:25800   (listed, honoured)
X-Forwarded-Host: 192.168.1.80:25800  Proto: https  -> fell back to the default    (https spelling not listed)
```

Other requirements: WebSockets are not used, so no upgrade handling is needed; do not
rewrite the path (the UI is served under `/jd-bank/...` and expects that prefix); allow
response bodies of a few MB (JD exports); keep the proxy read timeout at 60s or more,
since compose and validate calls wait on the inference host.

🔴 **Never set `CAS_SERVICE_FROM_REQUEST=true`.** It is a retired setting kept only so
that a deployment which sets it is refused rather than silently ignored. It derived the
return origin from the client's header with no validation.

---

## 6. NAT port-forwarding — read this before using one

A plain TCP port-forward (external `:7000` → internal `:25800`) **works**, but it changes
the origin, because **the port is part of the origin**. The forward's *external* port is
what the browser used, so `http://host:7000` is what belongs on the allowlist — not the
internal `:25800`.

A forward adds no proxy headers at all, so the browser's own `Host` is the only evidence
of the origin. That is why `Host` is read as well as `X-Forwarded-Host`.

Also, if you are testing a forward:

- **Most gateways do not hairpin.** Connecting to the public IP *from inside* the LAN
  will time out even when the forward is working perfectly. Test from a genuinely
  external network.
- **A configured forward rule is not proof of a working path.** Verify by reaching the
  app from outside and checking that the request appears in the app's own log (§7) — an
  external TCP probe reporting "open" while the log stays empty means something in
  between answered, not the app.
- **Pin the internal host's address.** A DHCP lease change silently invalidates the rule.
- For a data-centre deployment, prefer a reverse proxy with a real certificate over a
  port-forward. A forward gives you a plain-http origin, which production refuses.

---

## 7. Verification — run these, in order

On the box unless noted.

**1. The app answers locally**
```bash
curl -s http://127.0.0.1:25800/health          # expect: {"status":"ok"}
```

**2. Each public origin resolves to itself.** Repeat for every entry you configured —
this is the check that catches the §1 failure before users do:
```bash
curl -s -o /dev/null -D- \
  -H "Host: jdbank.its.sfu.ca" \
  -H "X-Forwarded-Host: jdbank.its.sfu.ca" \
  -H "X-Forwarded-Proto: https" \
  http://127.0.0.1:25800/jd-bank/ui/cas/login | grep -i '^location'
```
The `service=` parameter in the `Location` header **must be the origin you are testing**.
If it names a *different* host, that origin is not on the allowlist, and every user
arriving that way will be bounced to the fallback.

**3. The path from outside works end to end.** From a machine on a user network, load
`https://<fqdn>/jd-bank/ui/library`, sign in, and confirm the request arrived:
```bash
docker compose logs api --since 5m | grep cas
```
No log line means the traffic never reached the app — a network problem, not an app one.

**4. Nothing else is exposed.** From off-box:
```bash
nmap -Pn -p 25379,25432,25474,25687,25800 <host>    # only 25800 may be open
```

---

## 8. Symptom → cause

| symptom | cause |
|---|---|
| Sign-in completes at CAS, then times out on a **different hostname**, with `ticket=ST-…` in the URL | the origin the user arrived on is not in `ALLOWED_SERVICE_ORIGINS`; they were sent to the fallback |
| Works by FQDN, fails by short name (or the reverse) | one of the two spellings is missing from the allowlist |
| Worked on http, broke when TLS was added | the https spelling is a new origin; add it, and drop the http one |
| App refuses to start, log says "refusing to load settings" | a production posture violation — plain http, loopback, or a shipped default still in place. The message names the setting |
| External users time out, internal users are fine, app log empty | network path, not the app — forward rule, gateway firewall, or upstream NAT |
| `CAS ticket validation failed` | outbound 443 to `cas.sfu.ca` blocked, clock skew, or the service URL changed between login and validation |
| Compose or search slow/failing while everything else is fine | the Ollama host is unreachable |

---

## 9. Settings this guide refers to

Set in the environment file the install script reads; see [`.env.example`](../.env.example).

| setting | meaning |
|---|---|
| `ALLOWED_SERVICE_ORIGINS` | comma-separated list of every origin users reach the app on (§1) |
| `CAS_SERVICE_BASE_URL` | the fallback used when an arriving origin is not listed. **Point it at a host that actually answers** — a dead fallback turns a missing entry into an unexplainable timeout |
| `JD_API_BIND` / `JD_API_PORT` | where the API publishes on the host. Default `127.0.0.1:25800` |
| `OLLAMA_BASE_URL` / `ALLOWED_INFERENCE_HOSTS` | the inference host, and the hosts the app may ever send JD text to |
| `CAS_SERVICE_FROM_REQUEST` | retired. Must stay `false` |
| `CAS_VERIFY_TLS` | leave `true`. Flip only with a documented reason (container cert-chain issues) |

---

## 10. Worked example — the pre-data-centre box, and what it taught us

That box sat behind a consumer gateway with `external :7000 → 192.168.1.80:25800`. Three
distinct failures, all of which this guide exists to prevent:

1. **Users on the LAN could not sign in.** `192.168.1.80:25800` was not on the allowlist,
   so CAS returned them to the forward's external origin. A hosts-file entry did not help:
   the fallback carries port **7000**, and nothing on the internal host listens there. The
   port is part of the origin.
2. **The short name failed after the FQDN was fixed.** `aria-alien1:25800` and
   `aria-alien1.tail652d79.ts.net:25800` are different origins. Adding one did not add the
   other.
3. **The fallback was a host that could not answer**, so every miss produced a bare
   connection timeout on a URL carrying a valid ticket, instead of anything that pointed at
   the real cause. It is now a live host — which is why §9 says to keep it one.

Separately, on the network side: the forward stopped delivering traffic while its rule
remained visibly configured in the gateway UI; hairpin tests from inside gave false
negatives; and an external port probe reported "open" for a connection the app never
logged. Hence §6.
