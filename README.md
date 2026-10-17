# Customer Support Agent — Policy RAG + Human-Gated Refunds

One agent, two behaviors, split by what's actually at stake:

- **General questions** ("what's your return window", "do you ship
  internationally") are answered directly from a small policy knowledge
  base via retrieval. No human involved — this is the "operate
  autonomously within its lane" half.
- **Refund requests** are different. The agent looks up the real order,
  checks it against policy, drafts the specific action with its own
  justification — and then **always** stops and asks a human before
  anything executes. Money never moves without a person saying yes.

This is meant to demonstrate the actual shape of a support agent a
business could deploy: cheap and safe stuff is autonomous, anything
touching money is gated and backed by policy the agent itself retrieved
and cited — not a blanket "call a human for everything" cop-out, and not
a blanket "let the model decide" liability either.

## How it works

1. **Route** — the incoming message is classified as either a general
   question or a refund request (via Gemini function-calling, or a
   rule-based fallback with no API key).
2. **FAQ path** — retrieves the most relevant policy paragraphs from
   `policy_kb/` and answers from them (synthesized via Gemini if a key is
   set, otherwise the raw matched excerpts). Every answer logs which
   policy doc it came from.
3. **Refund path**:
   - Looks up the order in the mock order database (`orders.json`)
   - Checks it against policy: damaged/defective/wrong-item claims are
     eligible regardless of the return window; otherwise it checks the
     order age against the 30-day window
   - Drafts the proposed refund with its policy justification
   - **Always** presents it to a human for approval.
   - Only executes after a human approves.
4. **Web Interface** — `server.py` (a FastAPI backend) hosts the agent and serves the frontend. Chat interactions and admin refund approvals are processed via API endpoints, connecting the user interface to the core agent logic.
5. **Audit** — every question answered, refund proposed, human decision,
   and execution result is appended to `audit_log.jsonl`, timestamped,
   with a shared `run_id` per interaction.

### Architecture

```text
     +------------+       +-------------------+       +-------------+
     |   User     | <---> |   Web Interface   | <---> |   Agent     |
     +------------+       |   (FastAPI)       |       +-------------+
                          +-------------------+        /     |     \
                                                      /      |      \
                                             +-----------+ +-----------+ +-----------+
                                             | Policy KB | | Audit Log | | Orders DB |
                                             +-----------+ +-----------+ +-----------+
```


## Try it

No API key needed to see the full flow — it falls back to keyword
retrieval and a rule-based router:

### Option 1: Web Interface (Recommended)

```bash
pip install -r requirements.txt
python server.py
# Visit http://localhost:8000 in your browser
# http://localhost:8000/admin to approve or decline refund requests with reason
```

### Option 2: CLI

```bash
# FAQ — answered directly, no approval
python agent.py "what's your return window?"
python agent.py "do you ship internationally?"

# Refund — always gated
python agent.py "order A-1029 arrived broken, I want a refund"      # damaged -> eligible
python agent.py "I want a refund for order C-42, I just changed my mind"  # outside window -> not covered, still asks a human
python agent.py "refund order Z-999 please"                          # unknown order -> handled gracefully

python agent.py --show-trail
```

With `GEMINI_API_KEY` set, routing uses real function-calling and FAQ
answers are synthesized in natural language from the retrieved policy
context instead of shown as raw excerpts.

## Files

- `server.py` — FastAPI backend, handles API routes and static file serving
- `static/` — Frontend assets (`index.html`, `admin.html`, `tokens.css`)
- `agent.py` — routing, FAQ answering, refund flow, approval gate
- `retriever.py` — lightweight keyword-overlap retrieval over `policy_kb/`
- `tools.py` — refund schema, order lookup, policy eligibility logic
- `audit.py` — append-only JSONL audit trail
- `orders.json` — mock order database
- `policy_kb/` — return policy, refund policy, shipping FAQ (markdown)

## Notes on the retrieval

`retriever.py` is deliberately dependency-free keyword matching with
light stemming, not embeddings — it's here to make the _pattern_ (retrieve
→ ground the answer → cite the source) demoable with zero setup. For a
real deployment, swap `retrieve()` for actual embeddings — this is a
natural place to plug in the RAG bot from project 4.

## Extending this for a real portfolio piece

- Swap `execute_refund()` for a real payment processor call.
- Swap the CLI `input()` approval for a Slack/dashboard approval with a
  named approver instead of "human".
- Tier the gate by amount (auto-approve small, clearly-eligible refunds;
  always gate large or ambiguous ones) if you want to show policy nuance
  beyond "refunds always ask" — the eligibility check already produces
  the signal needed for that, it's just not wired to skip the gate here.
