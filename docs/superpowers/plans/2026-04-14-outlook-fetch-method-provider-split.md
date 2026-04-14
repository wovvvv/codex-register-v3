# Outlook Fetch-Method Provider Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit `outlook-imap` / `outlook-graph` provider families to the WebUI start forms, keep mixed `outlook` behavior intact, remove `outlook:no-token`, and make backend job selection honor `fetch_method` before applying rotation or fixed indexes.

**Architecture:** Keep the existing `mail.outlook` settings list as the single source of truth. Refactor the FastAPI job runner to parse provider families (`outlook`, `outlook-imap`, `outlook-graph`), filter configured Outlook accounts by `fetch_method`, and then apply rotation or `:N` against the filtered pool. Simplify the React provider-option builders and start-form hooks so they no longer depend on the no-token stats API, and expose the split providers directly in the Jobs and Dashboard selectors.

**Tech Stack:** Python 3.11, FastAPI, asyncio, React 18, Vite, Node built-in test runner, `unittest`

---

## File Structure

**Create:**
- `docs/superpowers/plans/2026-04-14-outlook-fetch-method-provider-split.md`
- `test/test_outlook_provider_split.py`

**Modify:**
- `src/webui/server.py`
- `webui_frontend/src/lib/cfworkerConfig.js`
- `webui_frontend/src/lib/providerOptions.test.js`
- `webui_frontend/src/pages/Dashboard.jsx`
- `webui_frontend/src/pages/Jobs.jsx`
- `webui_frontend/src/lib/api.js`

**Do Not Touch:**
- `test/test_outlook_no_token_rotation.py`
  Treat the existing untracked no-token test file as unrelated draft work in this dirty tree. Create a new focused test file for the split-provider behavior instead of rewriting or deleting that draft.

**Implementation Discipline:**
- Use `@superpowers:test-driven-development` for each code slice below.
- Use `@superpowers:verification-before-completion` before claiming the feature is done.

**Verification Commands:**
- `python3 -m unittest discover -s test -p 'test_outlook_provider_split.py' -v`
- `python3 -m py_compile src/webui/server.py`
- `node --test webui_frontend/src/lib/providerOptions.test.js`
- `npm --prefix webui_frontend run build`

### Task 1: Split Outlook Provider Selection In The Backend

**Files:**
- Create: `test/test_outlook_provider_split.py`
- Modify: `src/webui/server.py`

- [ ] **Step 1: Write failing backend tests for provider-family parsing and filtering**

Add pure helper-level tests in `test/test_outlook_provider_split.py` covering:

```python
def test_select_outlook_accounts_keeps_mixed_rotation_for_plain_outlook():
    ...

def test_select_outlook_accounts_filters_to_imap_accounts():
    ...

def test_select_outlook_accounts_filters_to_graph_accounts():
    ...

def test_parse_outlook_provider_selector_extracts_filtered_index():
    ...
```

The assertions must lock in these rules:

- `outlook` returns the full configured list
- `outlook-imap` returns only accounts whose `fetch_method` is `imap`
- `outlook-graph` returns only accounts whose `fetch_method` is `graph`
- `outlook-imap:1` parses as provider family `outlook-imap` with index `1`
- missing `fetch_method` defaults to `graph`

- [ ] **Step 2: Run the targeted backend test and verify it fails**

Run:

```bash
python3 -m unittest discover -s test -p 'test_outlook_provider_split.py' -v
```

Expected:

- FAIL because `src/webui/server.py` only supports `outlook` / `outlook:no-token`
- helper coverage for `outlook-imap` / `outlook-graph` does not exist yet

- [ ] **Step 3: Implement the minimal backend selector refactor**

In `src/webui/server.py`:

- replace the no-token-only `_select_outlook_accounts()` contract with split-provider filtering
- add a tiny parser such as `_parse_outlook_provider_selector(provider: str) -> tuple[str, Optional[int]]`
- keep `outlook:N` indexing against the full Outlook list
- make `outlook-imap:N` / `outlook-graph:N` index against the filtered list
- keep the final `OutlookMailClient(...)` constructor unchanged except for receiving the filtered `acc`

Concrete behavior to implement:

```python
family, fixed_index = _parse_outlook_provider_selector(job.provider)
accounts = _select_outlook_accounts(family, out_raw)
```

Error messages to preserve or introduce:

- `没有配置 Outlook 账户`
- `没有配置 fetch_method=imap 的 Outlook 账户`
- `没有配置 fetch_method=graph 的 Outlook 账户`
- filtered-index out-of-range errors must use the filtered pool count

- [ ] **Step 4: Run backend verification and confirm green**

Run:

```bash
python3 -m unittest discover -s test -p 'test_outlook_provider_split.py' -v
python3 -m py_compile src/webui/server.py
```

Expected:

- the new backend test file passes
- `py_compile` succeeds with no syntax errors

- [ ] **Step 5: Commit the backend split**

Run:

```bash
git add test/test_outlook_provider_split.py src/webui/server.py
git commit -m "feat: split outlook providers by fetch method"
```

### Task 2: Expose Split Outlook Providers In Frontend Option Builders

**Files:**
- Modify: `webui_frontend/src/lib/cfworkerConfig.js`
- Modify: `webui_frontend/src/lib/providerOptions.test.js`

- [ ] **Step 1: Add failing frontend tests for the new provider families**

Extend `webui_frontend/src/lib/providerOptions.test.js` to assert:

- `outlook:no-token` is absent from Settings, Dashboard, and Jobs option lists
- `outlook-imap` and `outlook-graph` appear in Dashboard and Jobs option lists
- mixed `outlook` still appears
- Jobs includes filtered fixed selectors like `outlook-imap:0` and `outlook-graph:0`
- Jobs labels include explicit prefixes such as `IMAP:` and `Graph:`

Example expectation shape:

```js
assert.equal(jobsOpts.some(([value]) => value === 'outlook-imap'), true)
assert.equal(jobsOpts.some(([value]) => value === 'outlook-graph:0'), true)
assert.equal(jobsOpts.some(([value]) => value === 'outlook:no-token'), false)
```

- [ ] **Step 2: Run the frontend test and verify it fails**

Run:

```bash
node --test webui_frontend/src/lib/providerOptions.test.js
```

Expected:

- FAIL because `cfworkerConfig.js` still emits `outlook:no-token`
- FAIL because split provider families and labels are not built yet

- [ ] **Step 3: Implement the new option-builder behavior**

In `webui_frontend/src/lib/cfworkerConfig.js`:

- remove `buildOutlookNoTokenLabel()` and all `outlookStats` label handling
- derive three pools from `settings['mail.outlook']`:
  - mixed: all accounts
  - imap: `fetch_method === 'imap'`
  - graph: `(fetch_method || 'graph') === 'graph'`
- keep Dashboard concise with top-level rotation options only:
  - `outlook`
  - `outlook-imap`
  - `outlook-graph`
- keep Jobs richer:
  - the three top-level rotation options above
  - mixed fixed selectors: `outlook:N`
  - filtered fixed selectors: `outlook-imap:N`, `outlook-graph:N`

Label rules:

- top level: `Outlook（全部 X 账户轮换）`, `Outlook IMAP（X 账户轮换）`, `Outlook Graph（X 账户轮换）`
- fixed rows: `└ IMAP: email@example.com`, `└ Graph: email@example.com`

- [ ] **Step 4: Run the frontend test and confirm green**

Run:

```bash
node --test webui_frontend/src/lib/providerOptions.test.js
```

Expected:

- all updated provider-option tests pass

- [ ] **Step 5: Commit the option-builder change**

Run:

```bash
git add webui_frontend/src/lib/cfworkerConfig.js webui_frontend/src/lib/providerOptions.test.js
git commit -m "feat: expose split outlook provider options"
```

### Task 3: Remove No-Token Stats Plumbing From Start Forms

**Files:**
- Modify: `webui_frontend/src/pages/Dashboard.jsx`
- Modify: `webui_frontend/src/pages/Jobs.jsx`
- Modify: `webui_frontend/src/lib/api.js`
- Modify: `src/webui/server.py`
- Modify: `webui_frontend/src/lib/providerOptions.test.js`

- [ ] **Step 1: Add failing assertions that the start forms no longer reference Outlook stats**

Use the existing source-reading style in `webui_frontend/src/lib/providerOptions.test.js` to add assertions such as:

```js
assert.doesNotMatch(readPage('Dashboard.jsx'), /getOutlookStats/)
assert.doesNotMatch(readPage('Jobs.jsx'), /getOutlookStats/)
assert.doesNotMatch(readPage('Dashboard.jsx'), /outlookStats/)
assert.doesNotMatch(readPage('Jobs.jsx'), /outlookStats/)
```

Also assert the frontend API wrapper no longer exposes `getOutlookStats`.

- [ ] **Step 2: Run the frontend test and verify it fails**

Run:

```bash
node --test webui_frontend/src/lib/providerOptions.test.js
```

Expected:

- FAIL because Dashboard, Jobs, and `api.js` still depend on the no-token stats path

- [ ] **Step 3: Remove the obsolete no-token stats chain**

Make the smallest clean-up set:

- in `Dashboard.jsx`, fetch only `api.getSettings()` inside `useProviderOptions()`
- in `Jobs.jsx`, fetch only `api.getSettings()` inside `useProviderOptions()`
- in `api.js`, remove `getOutlookStats`
- in `src/webui/server.py`, remove `_build_outlook_rotation_stats()` and the `/api/mail/outlook/stats` route if nothing else references them

Do not remove unrelated `accounts_mod` usage elsewhere in `src/webui/server.py`; only delete the no-token-specific code path that became dead after the provider split.

- [ ] **Step 4: Run frontend build and targeted verification**

Run:

```bash
node --test webui_frontend/src/lib/providerOptions.test.js
npm --prefix webui_frontend run build
```

Expected:

- provider-options tests pass
- Vite build completes successfully with no missing imports or dead API references

- [ ] **Step 5: Commit the no-token cleanup**

Run:

```bash
git add webui_frontend/src/pages/Dashboard.jsx webui_frontend/src/pages/Jobs.jsx webui_frontend/src/lib/api.js src/webui/server.py webui_frontend/src/lib/providerOptions.test.js
git commit -m "refactor: remove outlook no-token provider plumbing"
```

### Task 4: Final Verification And Regression Check

**Files:**
- Modify: none

- [ ] **Step 1: Re-run the full focused verification set**

Run:

```bash
python3 -m unittest discover -s test -p 'test_outlook_provider_split.py' -v
python3 -m py_compile src/webui/server.py
node --test webui_frontend/src/lib/providerOptions.test.js
npm --prefix webui_frontend run build
```

Expected:

- all Python and Node checks pass
- no syntax errors remain
- the frontend still builds after the provider-family split

- [ ] **Step 2: Perform a quick regression review of the user-facing provider values**

Manually inspect the affected logic and confirm:

- mixed `outlook` / `outlook:N` still exist
- `outlook-imap` / `outlook-graph` are exposed in start forms
- `outlook:no-token` is gone everywhere touched by this feature
- the backend selects fixed indexes against the correct pool
- no unrelated dirty-worktree files were reverted or renamed

- [ ] **Step 3: Summarize the implementation handoff**

Record in the final execution summary:

- which new providers were added
- that `outlook:no-token` was removed
- that filtered indexes are relative to the filtered pool, not the original list
- which verification commands were run successfully
