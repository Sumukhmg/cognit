# 🧠 COGNIT: The 100x Intelligent, Agent-Native Version Control System

> **A revolutionary, open-source, lightweight alternative to Git engineered specifically for Autonomous AI Agents, Multi-Agent Swarms, and LLM-assisted developers.**

---

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.8+](https://img.shields.io/badge/Python-3.8%2B-brightgreen.svg)](https://python.org)
[![Zero-Dependency Core](https://img.shields.io/badge/Dependencies-Zero%20(Pure%20Standard%20Lib)-success.svg)]()
[![Machine Readable](https://img.shields.io/badge/API-Native%20JSON--RPC%20%26%20REST-orange.svg)]()
[![Multi-Language AST](https://img.shields.io/badge/AST-Python%20%7C%20TS%2FJS%20%7C%20Go%20%7C%20Rust-blueviolet.svg)]()

---

## ⚡ The Manifesto: Why Git Fails AI Agents

Git was created in 2005 for human Linux kernel developers emailing text patches to mailing lists. In the age of AI coding agents and autonomous multi-agent swarms, Git's architecture is a bottleneck:

| Feature / Problem | Git (Human Era 2005) | Cognit 100x (Agent Era) |
| :--- | :--- | :--- |
| **Merge Engine** | Dumb Myers line-by-line diffs. Triggers cryptic `<<<<<<< HEAD` text conflicts when two agents touch nearby lines or append functions. | **AST-Aware Semantic 3-Way Merge**: Understands functions, classes, and symbols. Edits to disjoint symbols merge automatically with **zero conflict**, even if adjacent in source! |
| **Data Safety & Mental Model** | Staging vs Working Tree vs HEAD vs Reflog. `git reset --hard` causes catastrophic irreversible data loss when an agent makes a mistake. | **Transactional Micro-Checkpoints + Flight Recorder**: Every state is an immutable node in an append-only DAG. Continuous micro-snapshots allow safe millisecond rewinding. |
| **AI Provenance** | Commits only store `Author`, `Date`, and a string message. Zero metadata about who prompted it or why. | **Rich Agentic Provenance**: Every checkpoint records `model` (`gemini-3.8-flash`, `gpt-4o`, `claude`), `agent_id`, `goal` (task prompt), `reasoning` (plan/thoughts), `tools_used`, `test_status`, and `tokens_used`. |
| **Speculative Execution** | Stashing, creating, and switching Git branches is heavy, slow, and alters the working tree on disk. | **Speculative Trial Sandboxes & Tournaments**: Instant lightweight sandbox branches. Pit multiple LLMs or prompts against each other in automated benchmarks; auto-promote the winner! |
| **Token Economy** | `git diff` produces hundreds of raw lines of line diffs, flooding context windows and wasting thousands of LLM tokens. | **Hierarchical Token-Efficient Diffs**: 3 modes: `summary` (~20 tokens), `semantic` (~150 tokens), or `full` unified diff. Saves **80%+ context tokens** on agent queries. |
| **Context Window Prep** | Agents must manually read entire files or rely on naive search, wasting prompt tokens. | **`cognit context --goal "<task>"`**: Dependency-aware symbol extraction. Extracts only the relevant function signatures, types, and docstrings within a target token budget! |
| **Blast Radius & Impact** | Git has zero understanding of cross-file imports or symbol call graphs. | **`cognit impact <file_or_symbol>`**: Graph analysis computes direct dependents, transitive dependents, and **exact test suites to re-run** before committing! |
| **Multi-Agent Swarms** | Multiple agents working simultaneously on the same working tree collide and corrupt files. | **Virtual Workspaces & Intent Locks**: Isolated virtual working directories (`cognit workspace`) + distributed intent leases (`cognit lock`) for parallel swarms without disk bloat. |
| **Conflict Resolution** | Dumps syntax-breaking markers in files and crashes. Agents must manually parse raw text. | **Autonomous Synthesis Prompt Generator (`cognit resolve`)**: Generates an LLM synthesis prompt combining Base, Branch A, and Branch B goals and implementations for one-shot resolution. |
| **Code Lineage & Blame** | `git blame` only shows a commit hash. You have no idea *why* an agent wrote a line. | **`cognit explain <file> [symbol]`**: Traces the prompt lineage, agent reasoning, model version, and test status across every revision. |
| **Offline Transport** | Requires setting up Git daemons, SSH keys, or remote servers. | **Portable `.cgb` Bundles (`cognit bundle`)**: Package and transport repository histories as a single compressed file between air-gapped agents or over HTTP. |
| **Ecosystem Interop** | Fear of lock-in prevents teams from switching away from Git. | **Bidirectional Git Bridge**: Seamless `cognit git-bridge import` and `cognit git-bridge export` to sync with standard Git/GitHub repos. |

---

## 🛠️ CLI Quick Reference

```bash
# 1. Initialize & Status
cognit init --branch main
cognit status
cognit status --json

# 2. Transactional Agent Checkpoint
cognit checkpoint -m "Implement OAuth2 RS256 token verification" \
  --agent-id "coder-agent-1" \
  --model "gemini-3.8-flash" \
  --goal "Add secure JWT validation with 15m expiration" \
  --reasoning "Used pyjwt with cached public keys and custom claims validator" \
  --tools "replace_file_content,run_command" \
  --test-status "passed" \
  --tokens 350

# 3. Dependency Impact & Blast Radius Analysis
cognit impact utils.py
cognit impact utils.py:hash_password --json

# 4. Context Window Optimizer (Token Economy)
cognit context --goal "Refactor user authentication cache" --tokens 1200

# 5. Continuous Flight Recorder (Rollback & Timeline)
cognit flight-log
cognit rollback --steps 1

# 6. Multi-Agent Isolated Virtual Workspaces
cognit workspace create coder-1 --branch feature/auth
cognit workspace list
cognit workspace destroy coder-1

# 7. Speculative Multi-Model Tournaments
cognit tournament trial-gemini trial-gpt trial-claude --command "python -m unittest" --promote

# 8. Hierarchical Diffs
cognit diff --mode summary    # ~30 tokens
cognit diff --mode semantic   # AST symbol changes
cognit diff --mode full       # Line-by-line patch

# 9. AST-Aware 3-Way Semantic Merge
cognit merge feature/payments -m "Merge payment module"

# 10. Autonomous Conflict Resolution
cognit resolve prompt billing.py charge_card --goal-a "Stripe" --goal-b "PayPal"

# 11. Code Lineage & Prompt Blame
cognit explain billing.py charge_card

# 12. Portable Offline Archive Bundles
cognit bundle create release_v1.cgb --branch main
cognit bundle apply release_v1.cgb

# 13. Git / GitHub Bridge
cognit git-bridge import /path/to/git-repo
cognit git-bridge export /path/to/git-repo

# 14. Real-time Web Visualizer & REST Daemon
cognit serve --port 5050
```

---

## 🐍 Python SDK for AI Agent Developers

Cognit can be imported and controlled programmatically inside any agent framework (LangChain, AutoGen, CrewAI, LangGraph, or custom loops):

```python
from cognit import CognitRepo, AgentMetadata

# Initialize or connect to repo
repo = CognitRepo.init("./my-project")

# 1. Analyze change impact before editing
impact = repo.analyze_impact("billing.py:charge_card")
print(f"Risk Level: {impact.risk_level}")
print(f"Tests to re-run: {impact.affected_tests}")

# 2. Extract token-budgeted prompt context for LLM
prompt_context = repo.build_context("Implement discount coupon code logic", max_tokens=1000)

# 3. Make transactional checkpoint with reasoning
checkpoint = repo.create_checkpoint(
    message="Add coupon discount validation",
    author="Agent-Prometheus",
    agent_metadata=AgentMetadata(
        agent_id="agent-01",
        model="gemini-3.8-flash",
        goal="Add coupon discount validation",
        reasoning="Applied percentage and fixed-amount coupon calculations",
        test_status="passed",
        tokens_used=240,
    ),
)

# 4. Continuous flight recording
repo.record_micro_step("Refactored coupon validation regex", agent_id="agent-01")
```

---

## 🌐 Embedded Real-Time Web Visualizer

Run `cognit serve --port 5050` and open `http://127.0.0.1:5050`:
- **DAG & Provenance Timeline**: Interactive graph of checkpoints, agent reasoning cards, model badges, and token counters.
- **Blast Radius & Impact Graph**: Real-time cross-file dependency visualization and test recommendations.
- **Speculative Tournament Matrix**: Leaderboards comparing parallel model trials across pass rates, token costs, and code complexity.
- **Context Window Playground**: Interactive prompt context builder with token budget sliders.
- **Flight Recorder Slider**: Continuous micro-step rollback and syntax validation monitor.

---

## 🧪 Comprehensive Automated Test Suite

Cognit is verified by 21 unit tests covering storage, AST parsing, semantic merges, tournaments, flight recorder, workspaces, bundles, impact analysis, and the CLI:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

---

## 📄 License

Cognit is open source software licensed under the [MIT License](LICENSE).
Contributions, feedback, and pull requests are warmly welcomed!
