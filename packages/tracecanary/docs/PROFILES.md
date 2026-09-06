# Contract profiles

Profiles are ready-to-edit `tracecanary/v2` contracts with **synthetic** canary
values. They are starting points, not policies: a profile only checks the keys,
prefixes, pointers, and retention requirements listed below.

Every profile:

- pins `contract_version: "tracecanary/v2"`;
- pins `semantic_conventions_version: "opentelemetry/semconv/1.43.0"` (the only
  supported version);
- uses `TCANARY_`-prefixed canary values with a random hex suffix;
- parses through `tracecanary.contract.parse_contract`.

Use them from the command line:

```text
tracecanary profile list [--format human|json]
tracecanary profile show --profile gen-ai-baseline [--format human|json]
tracecanary profile create --profile gen-ai-baseline --output ./empty-dir
```

`profile create` writes `contract.json` into an **existing empty** directory and
refuses to overwrite anything.

`covered_attributes` below is exactly the value returned by
`tracecanary.profiles.describe(profile_id)["covered_attributes"]`:

| token form | meaning |
| --- | --- |
| `key:<k>` | exact forbidden attribute key, any scope |
| `key-prefix:<p>` | forbidden attribute key prefix, any scope |
| `path-prefix:<p>` | forbidden JSON-pointer prefix evaluated against populated scalars |
| `<scope>:<key>` | attribute key read at that scope (retained field or retention requirement) |
| `identity:<scope>:<key>` | attribute key read **only** to establish `matched_ratio` identity |

---

## gen-ai-baseline

- **Title:** GenAI baseline
- **Semantic conventions:** `opentelemetry/semconv/1.43.0`
- **Summary:** synthetic canaries for prompt, tool call arguments, tool call
  result, and end-user identifier leakage, with GenAI operational fields
  retained by an explicit retention requirement.
- **Canaries (synthetic):** prompt, tool call arguments, tool call result, end
  user identifier.

**Covered attributes**

```text
key-prefix:enduser.
key:gen_ai.prompt
key:gen_ai.tool.call.arguments
key:gen_ai.tool.call.result
path-prefix:/resourceSpans/*/scopeSpans/*/spans/*/attributes/*/value/bytesValue
resource:service.name
span:gen_ai.operation.name
```

**Retention requirements** (`tracecanary.retention/v1`)

| requirement_id | scope | key | value_types | minimum_count | comparison |
| --- | --- | --- | --- | --- | --- |
| `service-name` | resource | `service.name` | `stringValue` | 1 | `presence` |
| `operation-name` | span | `gen_ai.operation.name` | `stringValue` | 1 | `presence` |

**Not covered**

- No tool-call or conversation identifiers beyond the four canaries.
- No `gen_ai.usage.*`, `gen_ai.request.model`, or `gen_ai.response.*` checks.
- No HTTP, database, or messaging attributes.
- The `bytesValue` path prefix matches only span attribute bytes values, not
  resource, scope, event, or link bytes values.

---

## http-service-baseline

- **Title:** HTTP service baseline
- **Semantic conventions:** `opentelemetry/semconv/1.43.0`
- **Summary:** server and client HTTP spans; request method and route are
  retained, header attributes and structured header dumps are forbidden.
  Contains no GenAI attributes.
- **Canaries (synthetic):** authorization header, cookie header, query string.

**Covered attributes**

```text
key-prefix:http.request.header.
key-prefix:http.response.header.
key:http.request.header.authorization
key:http.request.header.cookie
key:http.response.header.set-cookie
path-prefix:/resourceSpans/*/scopeSpans/*/spans/*/attributes/*/value/kvlistValue/values/*/value/stringValue
resource:service.name
span:http.request.method
span:http.route
```

**Retention requirements** (`tracecanary.retention/v1`)

| requirement_id | scope | key | value_types | minimum_count | comparison |
| --- | --- | --- | --- | --- | --- |
| `request-method` | span | `http.request.method` | `stringValue` | 1 | `presence` |
| `route-count` | span | `http.route` | `stringValue` | 1 | `count` |

**Not covered**

- No GenAI, database, or messaging attributes.
- No `url.full`, `url.query`, or `url.path` key checks; the query-string canary
  only matches where the synthetic value was planted.
- The `kvlistValue` path prefix only flags string scalars nested one level
  inside a span attribute kvlist; header maps nested deeper are not matched.
- No `matched_ratio` comparison, so no per-service ratio regression is measured.

---

## database-client-baseline

- **Title:** Database client baseline
- **Semantic conventions:** `opentelemetry/semconv/1.43.0`
- **Summary:** database client spans; system name and query summary are
  retained, statement text and bound parameter attributes are forbidden.
- **Canaries (synthetic):** statement text, bound parameter, result row.

**Covered attributes**

```text
key-prefix:db.query.parameter.
key:db.query.text
key:db.statement
resource:service.name
span:db.query.summary
span:db.system.name
```

**Retention requirements** (`tracecanary.retention/v1`)

| requirement_id | scope | key | value_types | minimum_count | comparison |
| --- | --- | --- | --- | --- | --- |
| `db-system` | span | `db.system.name` | `stringValue` | 1 | `presence` |
| `query-summary-count` | span | `db.query.summary` | `stringValue` | 1 | `count` |

**Not covered**

- No forbidden JSON-pointer path prefix: this profile declares none, so a
  statement hidden in a nested `kvlistValue` is not flagged structurally.
- No `db.namespace`, `db.collection.name`, or `server.address` checks.
- No GenAI or HTTP attributes.
- No `matched_ratio` comparison.

---

## strict-safety-net

- **Title:** Strict safety net
- **Semantic conventions:** `opentelemetry/semconv/1.43.0`
- **Summary:** broadest profile; every GenAI, HTTP header, and database
  statement rule plus a `matched_ratio` retention requirement with declared
  matching keys and a declared denominator.
- **Canaries (synthetic):** prompt, tool call result, end-user identifier,
  request header.

**Covered attributes**

```text
identity:resource:service.name
key-prefix:db.query.parameter.
key-prefix:enduser.
key-prefix:http.request.header.
key-prefix:http.response.header.
key:db.query.text
key:db.statement
key:gen_ai.prompt
key:gen_ai.tool.call.arguments
key:gen_ai.tool.call.result
key:http.request.header.authorization
path-prefix:/resourceSpans/*/scopeSpans/*/spans/*/attributes/*/value/bytesValue
path-prefix:/resourceSpans/*/scopeSpans/*/spans/*/attributes/*/value/kvlistValue/values/*/value/stringValue
resource:service.name
span:gen_ai.operation.name
span:gen_ai.request.model
```

**Retention requirements** (`tracecanary.retention/v1`)

| requirement_id | scope | key | value_types | minimum_count | comparison |
| --- | --- | --- | --- | --- | --- |
| `operation-total` | span | `gen_ai.operation.name` | `stringValue` | 1 | `presence` |
| `model-annotated-operations` | span | `gen_ai.request.model` | `stringValue` | 1 | `matched_ratio` |

`model-annotated-operations` declares `matching_keys: [{"scope": "resource",
"key": "service.name"}]` and `denominator_requirement_id: operation-total`, so
the ratio is "spans of a service that name their model" over "spans of that
service that name their operation". `resource:service.name` is read only as
`identity:resource:service.name`, never as a privacy check.

This profile is deliberately strict: a trace that never sets
`gen_ai.request.model` fails `model-annotated-operations` with `TC010` on a
plain `check`, and a `diff` where the identity cannot be established (for
example, a resource without `service.name`) resolves as `TC014` / `unresolved`,
never as a pass.

**Not covered**

- No tool-call *arguments* canary; only the tool call result canary is planted.
- No `db.query.summary`, `http.route`, or `db.system.name` retention requirement.
- No messaging, RPC, or cloud attribute checks.
- `matched_ratio` compares only identities present in **both** populations; an
  identity that disappears entirely is reported as unresolved, not as a
  regression, so a service that stops exporting spans is not counted as a ratio
  drop.
