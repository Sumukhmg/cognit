"""Command Line Interface for Cognit: The Agent-Native Version Control System."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure Windows terminal doesn't crash on Unicode characters like ✓ or ●
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from cognit.agentic.explain import ExplainEngine
from cognit.agentic.intent_locks import IntentLockManager
from cognit.agentic.speculative import SpeculativeManager
from cognit.bridge.git_bridge import GitBridge
from cognit.core.models import AgentMetadata
from cognit.core.repo import CognitRepo

# Styling constants for terminal
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def print_json(data: Any, status: str = "ok") -> None:
    """Print structured JSON output for agents."""
    output = {
        "status": status,
        "data": data,
    }
    print(json.dumps(output, indent=2))


def handle_init(args: argparse.Namespace) -> None:
    branch = args.branch or "main"
    repo = CognitRepo.init(".", default_branch=branch)
    if args.json:
        print_json({
            "root_dir": str(repo.root_dir),
            "branch": branch,
            "cognit_dir": str(repo.cognit_dir),
        })
    else:
        print(f"{GREEN}{BOLD}✓ Initialized Cognit repository{RESET} on branch {CYAN}{branch}{RESET} at {repo.root_dir}")


def handle_status(args: argparse.Namespace) -> None:
    repo = CognitRepo.find_repo(".")
    statuses = repo.status()
    active_branch = repo.get_active_branch()
    head_cp = repo.get_head_checkpoint()

    if args.json:
        print_json({
            "branch": active_branch,
            "head_checkpoint": head_cp.to_dict() if head_cp else None,
            "files": [s.to_dict() for s in statuses],
        })
        return

    print(f"On branch: {CYAN}{BOLD}{active_branch}{RESET}")
    if head_cp:
        print(f"Latest checkpoint: {DIM}{head_cp.id[:8]}{RESET} - {head_cp.message} ({DIM}{head_cp.timestamp[:19]}{RESET})")
    else:
        print(f"{YELLOW}No checkpoints yet (empty repository){RESET}")

    added = [s for s in statuses if s.status == "added"]
    modified = [s for s in statuses if s.status == "modified"]
    deleted = [s for s in statuses if s.status == "deleted"]

    print()
    if not (added or modified or deleted):
        print(f"{GREEN}✓ Working tree clean. Ready for agent actions.{RESET}")
        return

    if modified:
        print(f"{YELLOW}{BOLD}Modified files:{RESET}")
        for s in modified:
            sym_info = f" {DIM}(symbols: {', '.join(s.symbols_changed)}){RESET}" if s.symbols_changed else ""
            print(f"  {YELLOW}~ {s.path}{sym_info}{RESET}")

    if added:
        print(f"{GREEN}{BOLD}Untracked / Added files:{RESET}")
        for s in added:
            print(f"  {GREEN}+ {s.path}{RESET}")

    if deleted:
        print(f"{RED}{BOLD}Deleted files:{RESET}")
        for s in deleted:
            print(f"  {RED}- {s.path}{RESET}")


def handle_checkpoint(args: argparse.Namespace) -> None:
    repo = CognitRepo.find_repo(".")
    tools = [t.strip() for t in args.tools.split(",")] if args.tools else []

    agent_meta = AgentMetadata(
        agent_id=args.agent_id or "human",
        model=args.model or "manual",
        goal=args.goal or "",
        reasoning=args.reasoning or "",
        tools_used=tools,
        test_status=args.test_status or "untested",
        tokens_used=args.tokens or 0,
    )

    cp = repo.create_checkpoint(
        message=args.message,
        author=args.author or "Agent",
        agent_metadata=agent_meta,
    )

    if args.json:
        print_json(cp.to_dict())
    else:
        print(f"{GREEN}{BOLD}✓ Checkpoint created:{RESET} {CYAN}{cp.id[:8]}{RESET}")
        print(f"  Message: {cp.message}")
        print(f"  Branch:  {cp.branch}")
        if agent_meta.model != "manual":
            print(f"  Agent:   {agent_meta.agent_id} ({agent_meta.model})")
        if agent_meta.goal:
            print(f"  Goal:    {agent_meta.goal}")


def handle_diff(args: argparse.Namespace) -> None:
    repo = CognitRepo.find_repo(".")
    target = getattr(args, "target_opt", None) or getattr(args, "target", None)
    source = getattr(args, "source", None)

    if target and source:
        diff_results = repo.diff_checkpoints(cid_base=target, cid_target=source, mode=args.mode)
    else:
        diff_results = repo.diff(mode=args.mode, target_checkpoint_id=target)

    if args.json:
        print_json([d.to_dict() for d in diff_results])
        return

    if not diff_results:
        print(f"{DIM}No changes detected.{RESET}")
        return

    if args.mode == "summary":
        print(f"{BOLD}Hierarchical Diff Summary:{RESET}")
        for d in diff_results:
            print(f"  {d.format_summary()}")
    elif args.mode == "semantic":
        print(f"{BOLD}Symbol-Level Semantic Diff:{RESET}")
        for d in diff_results:
            print(f"\n{CYAN}File: {d.file_path}{RESET}")
            if not d.symbol_diffs:
                print(f"  {DIM}(No AST symbol changes; lines modified: +{d.total_added}/-{d.total_deleted}){RESET}")
            for s in d.symbol_diffs:
                if s.change_type == "added":
                    print(f"  {GREEN}+ [{s.kind}] {s.name} (+{s.lines_added}){RESET}")
                elif s.change_type == "deleted":
                    print(f"  {RED}- [{s.kind}] {s.name} (-{s.lines_deleted}){RESET}")
                elif s.change_type == "modified":
                    print(f"  {YELLOW}~ [{s.kind}] {s.name} (+{s.lines_added}/-{s.lines_deleted}){RESET}")
                    if s.new_symbol and s.new_symbol.signature:
                        print(f"    {DIM}Signature: {s.new_symbol.signature}{RESET}")
    else:  # Full unified diff
        for d in diff_results:
            print(d.raw_unified_diff)


def handle_branch(args: argparse.Namespace) -> None:
    repo = CognitRepo.find_repo(".")
    if args.name:
        repo.create_branch(args.name)
        if args.switch:
            repo.switch_branch(args.name)
        if args.json:
            print_json({"created": args.name, "switched": args.switch})
        else:
            print(f"{GREEN}✓ Branch '{args.name}' created" + (" and switched to." if args.switch else "."))
    else:
        branches = repo.list_branches()
        if args.json:
            print_json(branches)
        else:
            print(f"{BOLD}Branches:{RESET}")
            for b in branches:
                prefix = f"{GREEN}* {RESET}" if b["is_active"] else "  "
                print(f"{prefix}{CYAN}{b['name']}{RESET} {DIM}({b['checkpoint_id'][:8] if b['checkpoint_id'] else 'empty'}){RESET} {b['message']}")


def handle_switch(args: argparse.Namespace) -> None:
    repo = CognitRepo.find_repo(".")
    repo.switch_branch(args.name)
    if args.json:
        print_json({"switched_to": args.name})
    else:
        print(f"{GREEN}✓ Switched to branch '{args.name}'{RESET}")


def handle_merge(args: argparse.Namespace) -> None:
    repo = CognitRepo.find_repo(".")
    cp = repo.merge_branches(
        source_branch=args.source,
        target_branch=args.target,
        message=args.message or f"Merge {args.source}",
    )
    if args.json:
        print_json(cp.to_dict())
    else:
        print(f"{GREEN}{BOLD}✓ Merged '{args.source}' -> '{cp.branch}'{RESET} ({cp.id[:8]})")
        print(f"  Status: {cp.agent_metadata.test_status}")


def handle_log(args: argparse.Namespace) -> None:
    repo = CognitRepo.find_repo(".")
    cps = repo.log(limit=args.limit, branch=args.branch, agent_id=args.agent)

    if args.json:
        print_json([c.to_dict() for c in cps])
        return

    print(f"{BOLD}Commit & Agent Provenance Log:{RESET}\n")
    for cp in cps:
        print(f"{CYAN}{BOLD}● Checkpoint: {cp.id[:8]}{RESET} {DIM}({cp.branch}){RESET}")
        print(f"  Author:    {cp.author}")
        print(f"  Date:      {cp.timestamp[:19]}")
        print(f"  Message:   {cp.message}")
        if cp.agent_metadata.agent_id != "human":
            print(f"  {MAGENTA}Agent:     {cp.agent_metadata.agent_id} | Model: {cp.agent_metadata.model}{RESET}")
        if cp.agent_metadata.goal:
            print(f"  {DIM}Goal:      {cp.agent_metadata.goal}{RESET}")
        if cp.agent_metadata.tokens_used:
            print(f"  {DIM}Tokens:    {cp.agent_metadata.tokens_used}{RESET}")
        print()


def handle_explain(args: argparse.Namespace) -> None:
    repo = CognitRepo.find_repo(".")
    engine = ExplainEngine(repo.db, repo)

    if args.symbol:
        lineage = engine.explain_symbol(args.file, args.symbol)
        if args.json:
            print_json([l.to_dict() for l in lineage])
        else:
            print(f"{BOLD}Lineage for Symbol '{args.symbol}' in {args.file}:{RESET}\n")
            if not lineage:
                print(f"{DIM}No recorded agent changes for symbol '{args.symbol}'.{RESET}")
            for l in lineage:
                print(f"{CYAN}Checkpoint {l.checkpoint_id[:8]}{RESET} ({l.timestamp[:19]})")
                print(f"  Agent:     {l.agent_id} ({l.model})")
                print(f"  Goal:      {l.goal}")
                print(f"  Reasoning: {l.reasoning}")
                print(f"  Tests:     {l.test_status}\n")
    else:
        file_exp = engine.explain_file(args.file)
        if args.json:
            print_json(file_exp)
        else:
            print(f"{BOLD}File Lineage Summary for {args.file}:{RESET}")
            print(f"  Checkpoints:    {file_exp['checkpoints_count']}")
            print(f"  Agents:         {', '.join(file_exp['agents_involved']) or 'human'}")
            print(f"  Models:         {', '.join(file_exp['models_used']) or 'none'}")
            print(f"  Total Tokens:   {file_exp['total_tokens_invested']}")
            print(f"  Recent Goals:")
            for g in file_exp["recent_goals"][:5]:
                print(f"    - {g}")


def handle_speculate(args: argparse.Namespace) -> None:
    repo = CognitRepo.find_repo(".")
    spec = SpeculativeManager(repo.db, repo)

    action = args.spec_action
    if action == "start":
        trial = spec.start_trial(args.name)
        if args.json:
            print_json(trial.to_dict())
        else:
            print(f"{GREEN}✓ Speculative trial '{trial.name}' started from {trial.base_checkpoint_id[:8]}{RESET}")
    elif action == "eval":
        trial = spec.evaluate_trial(args.name, test_command=args.command, score=args.score)
        if args.json:
            print_json(trial.to_dict())
        else:
            status_color = GREEN if trial.test_passed else RED
            print(f"Trial '{args.name}' evaluation: {status_color}{'PASSED' if trial.test_passed else 'FAILED'}{RESET} (Score: {trial.score})")
    elif action == "accept":
        cp = spec.accept_trial(args.name)
        if args.json:
            print_json(cp.to_dict())
        else:
            print(f"{GREEN}✓ Speculative trial '{args.name}' accepted and merged into current branch!{RESET}")
    elif action == "discard":
        trial = spec.discard_trial(args.name, reason=args.reason or "")
        if args.json:
            print_json(trial.to_dict())
        else:
            print(f"{YELLOW}✓ Speculative trial '{args.name}' discarded.{RESET}")
    elif action == "list":
        trials = spec.list_trials()
        if args.json:
            print_json([t.to_dict() for t in trials])
        else:
            print(f"{BOLD}Speculative Trials:{RESET}")
            for t in trials:
                print(f"  [{t.status.upper()}] {CYAN}{t.name}{RESET} (Base: {t.base_checkpoint_id[:8]}) Score: {t.score}")


def handle_lock(args: argparse.Namespace) -> None:
    repo = CognitRepo.find_repo(".")
    mgr = IntentLockManager(repo.db)
    action = args.lock_action

    if action == "acquire":
        success = mgr.acquire(args.target, agent_id=args.agent, goal=args.goal or "", ttl_seconds=args.ttl or 300)
        if args.json:
            print_json({"target": args.target, "acquired": success})
        else:
            if success:
                print(f"{GREEN}✓ Lock acquired on '{args.target}' for agent '{args.agent}'{RESET}")
            else:
                existing = mgr.check_target(args.target)
                print(f"{RED}✗ Lock denied for '{args.target}'. Currently held by '{existing.get('agent_id') if existing else 'another agent'}'{RESET}")
    elif action == "release":
        success = mgr.release(args.target, agent_id=args.agent)
        if args.json:
            print_json({"target": args.target, "released": success})
        else:
            print(f"{GREEN}✓ Lock released on '{args.target}'{RESET}" if success else f"{YELLOW}No lock held on '{args.target}' by '{args.agent}'{RESET}")
    elif action == "list":
        locks = mgr.list_active()
        if args.json:
            print_json(locks)
        else:
            print(f"{BOLD}Active Intent Locks:{RESET}")
            if not locks:
                print(f"  {DIM}(No active locks){RESET}")
            for l in locks:
                print(f"  {CYAN}{l['target']}{RESET} -> Agent: {l['agent_id']} (Goal: {l['goal']}) Expires: {l['expires_at'][:19]}")


def handle_time_travel(args: argparse.Namespace) -> None:
    repo = CognitRepo.find_repo(".")
    cp = repo.time_travel(args.checkpoint_id)
    if args.json:
        print_json(cp.to_dict())
    else:
        print(f"{GREEN}✓ Time-traveled to checkpoint {CYAN}{cp.id[:8]}{RESET}: {cp.message}")


def handle_undo(args: argparse.Namespace) -> None:
    repo = CognitRepo.find_repo(".")
    cp = repo.undo()
    if not cp:
        if args.json:
            print_json(None, status="error")
        else:
            print(f"{YELLOW}Cannot undo: no parent checkpoint exists.{RESET}")
        return

    if args.json:
        print_json(cp.to_dict())
    else:
        print(f"{GREEN}✓ Undone! Restored to checkpoint {CYAN}{cp.id[:8]}{RESET}: {cp.message}")


def handle_git_bridge(args: argparse.Namespace) -> None:
    repo = CognitRepo.find_repo(".")
    bridge = GitBridge(repo)
    action = args.bridge_action

    if action == "import":
        cnt = bridge.import_from_git(args.path, max_commits=args.max or 50)
        if args.json:
            print_json({"imported_commits": cnt})
        else:
            print(f"{GREEN}✓ Imported {cnt} commits from Git repository into Cognit.{RESET}")
    elif action == "export":
        cnt = bridge.export_to_git(args.path)
        if args.json:
            print_json({"exported_commits": cnt})
        else:
            print(f"{GREEN}✓ Exported {cnt} checkpoints from Cognit into Git repository at {args.path}.{RESET}")


def handle_impact(args: argparse.Namespace) -> None:
    repo = CognitRepo.find_repo(".")
    report = repo.analyze_impact(args.target)
    if args.json:
        print_json(report.to_dict())
    else:
        print(f"\n{BOLD}{CYAN}Dependency Impact Analysis:{RESET}")
        print(report.summary())


def handle_context(args: argparse.Namespace) -> None:
    repo = CognitRepo.find_repo(".")
    ctx = repo.build_context(args.goal, max_tokens=args.tokens or 1500)
    if args.json:
        print_json({"goal": args.goal, "context": ctx, "approx_tokens": len(ctx) // 4})
    else:
        print(ctx)


def handle_rollback(args: argparse.Namespace) -> None:
    repo = CognitRepo.find_repo(".")
    snap = repo.rollback_micro_step(steps=args.steps or 1)
    if not snap:
        if args.json:
            print_json({"error": "No micro-snapshots available to rollback"}, status="error")
        else:
            print(f"{YELLOW}No micro-snapshots available to rollback.{RESET}")
        return

    if args.json:
        print_json(snap.to_dict())
    else:
        print(f"{GREEN}✓ Rolled back {args.steps or 1} step(s) to step #{snap.step_index}{RESET} ({snap.action})")


def handle_flight_log(args: argparse.Namespace) -> None:
    from cognit.agentic.recorder import FlightRecorder
    repo = CognitRepo.find_repo(".")
    recorder = FlightRecorder(repo)
    timeline = recorder.get_timeline()
    if args.json:
        print_json([s.to_dict() for s in timeline])
    else:
        print(f"{BOLD}Agent Flight Recorder Timeline ({len(timeline)} steps):{RESET}")
        if not timeline:
            print(f"  {DIM}(Flight recorder log is currently empty){RESET}")
        for s in timeline[-20:]:
            syntax_str = f"{GREEN}valid{RESET}" if s.syntax_valid else f"{RED}syntax error{RESET}"
            print(f"  Step #{s.step_index} [{s.timestamp[11:19]}] {CYAN}{s.agent_id}{RESET}: {s.action} ({syntax_str})")


def handle_workspace(args: argparse.Namespace) -> None:
    from cognit.agentic.workspace import WorkspaceManager
    repo = CognitRepo.find_repo(".")
    wm = WorkspaceManager(repo)
    action = args.ws_action

    if action == "create":
        ws = wm.create_workspace(args.agent_id, branch_name=args.branch)
        if args.json:
            print_json(ws.to_dict())
        else:
            print(f"{GREEN}✓ Created isolated workspace for '{ws.agent_id}' at {ws.workspace_dir}{RESET}")
            print(f"  Branch: {CYAN}{ws.branch_name}{RESET}")
    elif action == "list":
        workspaces = wm.list_workspaces()
        if args.json:
            print_json([w.to_dict() for w in workspaces])
        else:
            print(f"{BOLD}Active Agent Workspaces:{RESET}")
            if not workspaces:
                print(f"  {DIM}(No active workspaces){RESET}")
            for w in workspaces:
                print(f"  {CYAN}{w.agent_id}{RESET} -> Branch: {w.branch_name} ({w.workspace_dir})")
    elif action == "destroy":
        res = wm.destroy_workspace(args.agent_id)
        if args.json:
            print_json({"destroyed": res})
        else:
            print(f"{GREEN}✓ Destroyed workspace for '{args.agent_id}'{RESET}" if res else f"{YELLOW}Workspace not found{RESET}")


def handle_tournament(args: argparse.Namespace) -> None:
    from cognit.agentic.tournament import SpeculativeTournament
    repo = CognitRepo.find_repo(".")
    tourney = SpeculativeTournament(repo)
    scorecards = tourney.evaluate_candidates(args.trials, test_command=args.command)

    if args.promote and scorecards and scorecards[0].test_passed:
        merged = tourney.promote_winner(scorecards)
        winner_name = scorecards[0].trial_name
    else:
        merged = None
        winner_name = None

    if args.json:
        print_json({
            "leaderboard": [s.to_dict() for s in scorecards],
            "winner_promoted": winner_name,
            "merge_checkpoint": merged.id if merged else None,
        })
    else:
        print(f"\n{BOLD}{MAGENTA}🏆 Speculative Tournament Leaderboard:{RESET}")
        for s in scorecards:
            status_color = GREEN if s.test_passed else RED
            print(f"  Rank #{s.rank} | {CYAN}{s.trial_name}{RESET} (Model: {s.model})")
            print(f"    Score: {BOLD}{s.score}{RESET} | Status: {status_color}{'PASSED' if s.test_passed else 'FAILED'}{RESET} | Tokens: {s.tokens_used}")
            print(f"    Diff: +{s.lines_added}/-{s.lines_deleted} lines")

        if merged:
            print(f"\n{GREEN}✓ Top candidate '{winner_name}' automatically promoted to active branch! ({merged.id[:8]}){RESET}")


def handle_bundle(args: argparse.Namespace) -> None:
    from cognit.core.bundle import BundleManager
    repo = CognitRepo.find_repo(".")
    bm = BundleManager(repo)
    action = args.bundle_action

    if action == "create":
        cnt = bm.create_bundle(args.file, branch_name=args.branch)
        if args.json:
            print_json({"bundle_file": args.file, "checkpoints_packed": cnt})
        else:
            print(f"{GREEN}✓ Created offline bundle '{args.file}' with {cnt} checkpoints.{RESET}")
    elif action == "apply":
        res = bm.apply_bundle(args.file)
        if args.json:
            print_json(res)
        else:
            print(f"{GREEN}✓ Applied bundle '{args.file}' on branch '{res['branch']}' ({res['objects_imported']} objects imported).{RESET}")


def handle_resolve(args: argparse.Namespace) -> None:
    from cognit.agentic.resolver import ConflictResolver
    from cognit.semantic.semantic_merge import ConflictDetail
    repo = CognitRepo.find_repo(".")
    resolver = ConflictResolver(repo)

    if args.resolve_action == "prompt":
        # Generate prompt for a file/symbol
        detail = ConflictDetail(
            file_path=args.file,
            symbol_name=args.symbol,
            kind="function",
            base_snippet=args.base or "",
            ours_snippet=args.ours or "",
            theirs_snippet=args.theirs or "",
            reason="Concurrent modifications by two agents",
        )
        prompt = resolver.generate_synthesis_prompt(detail, goal_a=args.goal_a or "", goal_b=args.goal_b or "")
        if args.json:
            print_json({"prompt": prompt})
        else:
            print(prompt)
    elif args.resolve_action == "apply":
        success = resolver.apply_symbol_resolution(args.file, args.symbol, args.code)
        if args.json:
            print_json({"applied": success})
        else:
            print(f"{GREEN}✓ Conflict resolution applied for '{args.symbol}' in {args.file}{RESET}" if success else f"{RED}Failed to locate conflict marker{RESET}")


def handle_serve(args: argparse.Namespace) -> None:
    from cognit.server.daemon import start_server
    start_server(port=args.port or 5050, host=args.host or "127.0.0.1")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cognit",
        description="Cognit: The Intelligent, Agent-Native Version Control System",
    )
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON for agents")
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # init
    p_init = subparsers.add_parser("init", help="Initialize a new Cognit repository")
    p_init.add_argument("--branch", "-b", help="Default branch name (default: main)")
    p_init.add_argument("--json", action="store_true")

    # status
    p_status = subparsers.add_parser("status", help="Show working tree status and symbol changes")
    p_status.add_argument("--json", action="store_true")

    # checkpoint (commit/snap)
    for name in ["checkpoint", "commit", "snap"]:
        p_cp = subparsers.add_parser(name, help="Record a transactional checkpoint with agent metadata")
        p_cp.add_argument("-m", "--message", required=True, help="Checkpoint message")
        p_cp.add_argument("--author", "-a", help="Author name")
        p_cp.add_argument("--agent-id", help="ID or role of AI agent")
        p_cp.add_argument("--model", help="LLM model (e.g. gemini-3.8-flash, gpt-4o)")
        p_cp.add_argument("--goal", help="Task prompt or goal")
        p_cp.add_argument("--reasoning", help="Agent reasoning / thoughts")
        p_cp.add_argument("--tools", help="Comma-separated tools invoked")
        p_cp.add_argument("--test-status", help="Test status: passed, failed, untested")
        p_cp.add_argument("--tokens", type=int, help="Tokens used in generation")
        p_cp.add_argument("--json", action="store_true")

    # diff
    p_diff = subparsers.add_parser("diff", help="Show hierarchical, semantic, or unified diffs")
    p_diff.add_argument("target", nargs="?", help="Base checkpoint or branch to diff against (optional)")
    p_diff.add_argument("source", nargs="?", help="Second checkpoint or branch to diff two commits (optional)")
    p_diff.add_argument("--mode", choices=["summary", "semantic", "full"], default="summary", help="Diff detail level")
    p_diff.add_argument("--target", dest="target_opt", help="Target checkpoint ID or branch to diff against")
    p_diff.add_argument("--json", action="store_true")

    # branch
    p_branch = subparsers.add_parser("branch", help="List or create branches")
    p_branch.add_argument("name", nargs="?", help="Branch name to create")
    p_branch.add_argument("--switch", "-s", action="store_true", help="Switch to branch after creation")
    p_branch.add_argument("--json", action="store_true")

    # switch
    for name in ["switch", "checkout"]:
        p_sw = subparsers.add_parser(name, help="Switch active branch")
        p_sw.add_argument("name", help="Branch name to switch to")
        p_sw.add_argument("--json", action="store_true")

    # merge
    p_merge = subparsers.add_parser("merge", help="Perform AST-aware 3-way semantic merge")
    p_merge.add_argument("source", help="Source branch to merge from")
    p_merge.add_argument("--target", help="Target branch (default: active branch)")
    p_merge.add_argument("-m", "--message", help="Merge checkpoint message")
    p_merge.add_argument("--json", action="store_true")

    # log
    p_log = subparsers.add_parser("log", help="Show commit graph and agent provenance")
    p_log.add_argument("--limit", "-n", type=int, default=50, help="Max entries")
    p_log.add_argument("--branch", "-b", help="Filter by branch")
    p_log.add_argument("--agent", help="Filter by agent ID")
    p_log.add_argument("--json", action="store_true")

    # explain
    p_explain = subparsers.add_parser("explain", help="Trace prompts and reasoning behind code")
    p_explain.add_argument("file", help="File path to explain")
    p_explain.add_argument("symbol", nargs="?", help="Symbol name (function or class)")
    p_explain.add_argument("--json", action="store_true")

    # speculate
    p_spec = subparsers.add_parser("speculate", help="Manage speculative exploration trials")
    spec_sub = p_spec.add_subparsers(dest="spec_action", required=True)

    p_sp_start = spec_sub.add_parser("start", help="Start a new speculative trial")
    p_sp_start.add_argument("name", help="Trial name")
    p_sp_start.add_argument("--json", action="store_true")

    p_sp_eval = spec_sub.add_parser("eval", help="Evaluate a trial")
    p_sp_eval.add_argument("name", help="Trial name")
    p_sp_eval.add_argument("--command", help="Test command to run")
    p_sp_eval.add_argument("--score", type=float, help="Evaluation score")
    p_sp_eval.add_argument("--json", action="store_true")

    p_sp_accept = spec_sub.add_parser("accept", help="Accept trial and promote to branch")
    p_sp_accept.add_argument("name", help="Trial name")
    p_sp_accept.add_argument("--json", action="store_true")

    p_sp_discard = spec_sub.add_parser("discard", help="Discard trial")
    p_sp_discard.add_argument("name", help="Trial name")
    p_sp_discard.add_argument("--reason", help="Reason for discarding")
    p_sp_discard.add_argument("--json", action="store_true")

    p_sp_list = spec_sub.add_parser("list", help="List all trials")
    p_sp_list.add_argument("--json", action="store_true")

    # lock
    p_lock = subparsers.add_parser("lock", help="Manage multi-agent intent locks")
    lock_sub = p_lock.add_subparsers(dest="lock_action", required=True)

    p_lk_acq = lock_sub.add_parser("acquire", help="Acquire a lock")
    p_lk_acq.add_argument("target", help="File or symbol target")
    p_lk_acq.add_argument("--agent", required=True, help="Agent ID")
    p_lk_acq.add_argument("--goal", help="Agent goal")
    p_lk_acq.add_argument("--ttl", type=int, default=300, help="TTL in seconds")
    p_lk_acq.add_argument("--json", action="store_true")

    p_lk_rel = lock_sub.add_parser("release", help="Release a lock")
    p_lk_rel.add_argument("target", help="File or symbol target")
    p_lk_rel.add_argument("--agent", required=True, help="Agent ID")
    p_lk_rel.add_argument("--json", action="store_true")

    p_lk_list = lock_sub.add_parser("list", help="List active locks")
    p_lk_list.add_argument("--json", action="store_true")

    # time-travel
    p_tt = subparsers.add_parser("time-travel", help="Restore working tree to an exact checkpoint")
    p_tt.add_argument("checkpoint_id", help="Target checkpoint ID")
    p_tt.add_argument("--json", action="store_true")

    # undo
    p_undo = subparsers.add_parser("undo", help="Safely undo to parent checkpoint")
    p_undo.add_argument("--json", action="store_true")

    # git-bridge
    p_bridge = subparsers.add_parser("git-bridge", help="Sync with standard Git repositories")
    bridge_sub = p_bridge.add_subparsers(dest="bridge_action", required=True)

    p_br_imp = bridge_sub.add_parser("import", help="Import from Git repository")
    p_br_imp.add_argument("path", help="Path to git repo")
    p_br_imp.add_argument("--max", type=int, default=50, help="Max commits to import")
    p_br_imp.add_argument("--json", action="store_true")

    p_br_exp = bridge_sub.add_parser("export", help="Export to Git repository")
    p_br_exp.add_argument("path", help="Target path to git repo")
    p_br_exp.add_argument("--json", action="store_true")

    # impact
    p_impact = subparsers.add_parser("impact", help="Analyze blast radius and downstream dependencies")
    p_impact.add_argument("target", help="File or symbol target (e.g. 'utils.py' or 'utils.py:hash_password')")
    p_impact.add_argument("--json", action="store_true")

    # context
    p_ctx = subparsers.add_parser("context", help="Extract compact token-budgeted prompt context")
    p_ctx.add_argument("--goal", required=True, help="Task goal/prompt")
    p_ctx.add_argument("--tokens", type=int, default=1500, help="Target token budget (default: 1500)")
    p_ctx.add_argument("--json", action="store_true")

    # rollback
    p_roll = subparsers.add_parser("rollback", help="Roll back working tree by N micro-snapshots")
    p_roll.add_argument("--steps", type=int, default=1, help="Number of micro-steps to rollback (default: 1)")
    p_roll.add_argument("--json", action="store_true")

    # flight-log
    p_fl = subparsers.add_parser("flight-log", help="Inspect continuous flight recorder timeline")
    p_fl.add_argument("--json", action="store_true")

    # workspace
    p_ws = subparsers.add_parser("workspace", help="Manage isolated multi-agent workspaces")
    ws_sub = p_ws.add_subparsers(dest="ws_action", required=True)
    p_ws_cr = ws_sub.add_parser("create", help="Create workspace for an agent")
    p_ws_cr.add_argument("agent_id", help="Agent identifier")
    p_ws_cr.add_argument("--branch", help="Branch name (default: agents/<agent_id>)")
    p_ws_cr.add_argument("--json", action="store_true")

    p_ws_ls = ws_sub.add_parser("list", help="List active agent workspaces")
    p_ws_ls.add_argument("--json", action="store_true")

    p_ws_rm = ws_sub.add_parser("destroy", help="Destroy agent workspace")
    p_ws_rm.add_argument("agent_id", help="Agent identifier")
    p_ws_rm.add_argument("--json", action="store_true")

    # tournament
    p_tourn = subparsers.add_parser("tournament", help="Rank and promote speculative candidate trials")
    p_tourn.add_argument("trials", nargs="+", help="Names of trial branches to evaluate")
    p_tourn.add_argument("--command", help="Evaluation / test command")
    p_tourn.add_argument("--promote", action="store_true", help="Auto-promote winning candidate to active branch")
    p_tourn.add_argument("--json", action="store_true")

    # bundle
    p_bnd = subparsers.add_parser("bundle", help="Create or apply portable offline repository bundles")
    bnd_sub = p_bnd.add_subparsers(dest="bundle_action", required=True)
    p_bnd_cr = bnd_sub.add_parser("create", help="Create a .cgb bundle file")
    p_bnd_cr.add_argument("file", help="Output bundle path (.cgb)")
    p_bnd_cr.add_argument("--branch", help="Branch to package (default: active branch)")
    p_bnd_cr.add_argument("--json", action="store_true")

    p_bnd_ap = bnd_sub.add_parser("apply", help="Apply a .cgb bundle file")
    p_bnd_ap.add_argument("file", help="Path to bundle file")
    p_bnd_ap.add_argument("--json", action="store_true")

    # resolve
    p_res = subparsers.add_parser("resolve", help="Autonomous conflict resolver and prompt generator")
    res_sub = p_res.add_subparsers(dest="resolve_action", required=True)
    p_res_pr = res_sub.add_parser("prompt", help="Generate synthesis prompt for an LLM to resolve conflict")
    p_res_pr.add_argument("file", help="File with conflict")
    p_res_pr.add_argument("symbol", help="Conflicting symbol name")
    p_res_pr.add_argument("--base", help="Base code snippet")
    p_res_pr.add_argument("--ours", help="Ours code snippet")
    p_res_pr.add_argument("--theirs", help="Theirs code snippet")
    p_res_pr.add_argument("--goal-a", help="Goal of branch A")
    p_res_pr.add_argument("--goal-b", help="Goal of branch B")
    p_res_pr.add_argument("--json", action="store_true")

    p_res_ap = res_sub.add_parser("apply", help="Apply resolved code for a symbol")
    p_res_ap.add_argument("file", help="File path")
    p_res_ap.add_argument("symbol", help="Symbol name")
    p_res_ap.add_argument("--code", required=True, help="Resolved code block")
    p_res_ap.add_argument("--json", action="store_true")

    # serve
    p_serve = subparsers.add_parser("serve", help="Launch web visualizer and JSON-RPC API daemon")
    p_serve.add_argument("--port", type=int, default=5050, help="Port to listen on (default: 5050)")
    p_serve.add_argument("--host", default="127.0.0.1", help="Host interface (default: 127.0.0.1)")

    args = parser.parse_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(1)

    try:
        if args.subcommand == "init":
            handle_init(args)
        elif args.subcommand == "status":
            handle_status(args)
        elif args.subcommand in ("checkpoint", "commit", "snap"):
            handle_checkpoint(args)
        elif args.subcommand == "diff":
            handle_diff(args)
        elif args.subcommand == "branch":
            handle_branch(args)
        elif args.subcommand in ("switch", "checkout"):
            handle_switch(args)
        elif args.subcommand == "merge":
            handle_merge(args)
        elif args.subcommand == "log":
            handle_log(args)
        elif args.subcommand == "explain":
            handle_explain(args)
        elif args.subcommand == "speculate":
            handle_speculate(args)
        elif args.subcommand == "lock":
            handle_lock(args)
        elif args.subcommand == "time-travel":
            handle_time_travel(args)
        elif args.subcommand == "undo":
            handle_undo(args)
        elif args.subcommand == "git-bridge":
            handle_git_bridge(args)
        elif args.subcommand == "impact":
            handle_impact(args)
        elif args.subcommand == "context":
            handle_context(args)
        elif args.subcommand == "rollback":
            handle_rollback(args)
        elif args.subcommand == "flight-log":
            handle_flight_log(args)
        elif args.subcommand == "workspace":
            handle_workspace(args)
        elif args.subcommand == "tournament":
            handle_tournament(args)
        elif args.subcommand == "bundle":
            handle_bundle(args)
        elif args.subcommand == "resolve":
            handle_resolve(args)
        elif args.subcommand == "serve":
            handle_serve(args)
    except Exception as e:
        if getattr(args, "json", False):
            print_json({"error": str(e)}, status="error")
        else:
            print(f"{RED}{BOLD}Error:{RESET} {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
