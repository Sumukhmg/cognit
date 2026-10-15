"""Example: Demonstrating how an autonomous AI coding agent uses Cognit."""

import tempfile
from pathlib import Path
from cognit import CognitRepo, AgentMetadata


def run_agent_demonstration():
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"\n1. Initializing Cognit repository at {tmpdir}...")
        repo = CognitRepo.init(tmpdir, default_branch="main")

        # Step 1: Agent receives task prompt
        prompt = "Create a robust user profile service with email validation and avatar generation"
        print(f"\n2. Agent received prompt: '{prompt}'")

        # Agent writes initial code
        service_code = '''import re

def validate_email(email: str) -> bool:
    """Validate user email format."""
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\\.[a-zA-Z0-9-.]+$"
    return bool(re.match(pattern, email))

def generate_avatar_url(username: str) -> str:
    """Return default avatar for username."""
    return f"https://api.dicebear.com/7.x/identicon/svg?seed={username}"
'''
        service_file = Path(tmpdir) / "profile_service.py"
        service_file.write_text(service_code, encoding="utf-8")

        # Step 2: Agent checks status
        status = repo.status()
        print("\n3. Agent checks working tree status:")
        for s in status:
            if s.status != "unmodified":
                print(f"   [{s.status.upper()}] {s.path}")

        # Step 3: Agent saves transactional checkpoint with reasoning and token cost
        cp1 = repo.create_checkpoint(
            message="Implement email validation and avatar generation",
            author="Gemini Assistant",
            agent_metadata=AgentMetadata(
                agent_id="agent-coder-1",
                model="gemini-3.8-flash",
                goal=prompt,
                reasoning="Used compiled regex for RFC 5322 email matching and DiceBear public SVG avatar API",
                tools_used=["write_to_file", "run_command"],
                test_status="passed",
                tokens_used=340,
            ),
        )
        print(f"\n4. Created checkpoint {cp1.id[:8]} with rich metadata:")
        print(f"   Model: {cp1.agent_metadata.model} | Tokens: {cp1.agent_metadata.tokens_used}")

        # Step 4: Agent receives follow-up prompt: add password hashing
        print("\n5. Agent receives follow-up prompt: 'Add bcrypt password hashing'")
        updated_code = service_code + '''
def hash_password(password: str) -> str:
    """Compute secure SHA-256 hash placeholder."""
    import hashlib
    return hashlib.sha256(password.encode("utf-8")).hexdigest()
'''
        service_file.write_text(updated_code, encoding="utf-8")

        # Step 5: Token-efficient diff for context window
        diffs = repo.diff(mode="summary")
        print("\n6. Token-efficient diff summary (saves 85%+ context tokens for LLMs):")
        for d in diffs:
            print(f"   {d.format_summary()}")

        cp2 = repo.create_checkpoint(
            message="Add password hashing",
            author="Gemini Assistant",
            agent_metadata=AgentMetadata(
                agent_id="agent-coder-1",
                model="gemini-3.8-flash",
                goal="Add bcrypt password hashing",
                reasoning="Implemented SHA-256 password digest",
                test_status="passed",
                tokens_used=180,
            ),
        )
        print(f"\n7. Created checkpoint {cp2.id[:8]}")

        # Step 6: Code Explainability & Prompt Blame
        from cognit.agentic.explain import ExplainEngine
        explain = ExplainEngine(repo.db, repo)
        lineage = explain.explain_symbol("profile_service.py", "validate_email")
        print("\n8. Prompt Blame (`cognit explain profile_service.py validate_email`):")
        for record in lineage:
            print(f"   Checkpoint: {record.checkpoint_id[:8]} by {record.agent_id} ({record.model})")
            print(f"   Goal:       {record.goal}")
            print(f"   Reasoning:  {record.reasoning}")

        print("\n[OK] Agent workflow demonstration complete successfully!")


if __name__ == "__main__":
    run_agent_demonstration()
