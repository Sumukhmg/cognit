"""Example: Multi-agent swarm simulation with intent locks and AST-aware auto-merging."""

import tempfile
from pathlib import Path
from cognit import CognitRepo, AgentMetadata
from cognit.agentic.intent_locks import IntentLockManager


def run_swarm_simulation():
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"\n1. Initializing Swarm Repository at {tmpdir}...")
        repo = CognitRepo.init(tmpdir, default_branch="main")
        locks = IntentLockManager(repo.db)

        # Base billing module
        billing_file = Path(tmpdir) / "billing.py"
        base_code = '''"""Billing and checkout system."""

def calculate_subtotal(items):
    return sum(item["price"] * item["qty"] for item in items)
'''
        billing_file.write_text(base_code, encoding="utf-8")
        repo.create_checkpoint("Initial billing module", author="Swarm Orchestrator")
        print("2. Base billing module established on 'main'.")

        # Swarm Agent 1 (Payment Agent): Wants to add charge_card
        print("\n3. Agent-Payments attempting to lock 'billing.py:charge_card'...")
        lock1_success = locks.acquire("billing.py:charge_card", agent_id="agent-payments", goal="Add Stripe credit card charging", ttl_seconds=600)
        print(f"   Lock acquired: {lock1_success}")

        # Swarm Agent 2 (Refunds Agent): Wants to add refund_card
        print("\n4. Agent-Refunds attempting to lock 'billing.py:refund_card'...")
        lock2_success = locks.acquire("billing.py:refund_card", agent_id="agent-refunds", goal="Add automated refunds processing", ttl_seconds=600)
        print(f"   Lock acquired: {lock2_success}")

        # Check collision prevention: What if Agent 3 tries to grab charge_card?
        print("\n5. Agent-Colliding attempting to lock already reserved 'billing.py:charge_card'...")
        lock3_success = locks.acquire("billing.py:charge_card", agent_id="agent-colliding", goal="Duplicate work attempt", ttl_seconds=600)
        print(f"   Lock acquired: {lock3_success} (Prevented duplicate work collision!)")

        # Agent 1 works on branch feature/payments
        print("\n6. Agent-Payments builds feature/payments...")
        repo.create_branch("feature/payments")
        repo.switch_branch("feature/payments")
        agent1_code = base_code + '''
def charge_card(customer_id, amount_cents):
    """Charge customer via payment gateway."""
    return {"status": "success", "charge_id": f"ch_{customer_id[:6]}"}
'''
        billing_file.write_text(agent1_code, encoding="utf-8")
        repo.create_checkpoint(
            "Add charge_card implementation",
            author="Agent-Payments",
            agent_metadata=AgentMetadata(
                agent_id="agent-payments",
                model="gemini-3.8-flash",
                goal="Add Stripe credit card charging",
                test_status="passed",
            )
        )
        locks.release("billing.py:charge_card", agent_id="agent-payments")

        # Agent 2 works on branch feature/refunds
        print("\n7. Agent-Refunds builds feature/refunds...")
        repo.switch_branch("main")
        repo.create_branch("feature/refunds")
        repo.switch_branch("feature/refunds")
        agent2_code = base_code + '''
def refund_card(charge_id, amount_cents):
    """Issue customer refund."""
    return {"status": "refunded", "refund_id": f"re_{charge_id[:6]}"}
'''
        billing_file.write_text(agent2_code, encoding="utf-8")
        repo.create_checkpoint(
            "Add refund_card implementation",
            author="Agent-Refunds",
            agent_metadata=AgentMetadata(
                agent_id="agent-refunds",
                model="gemini-3.8-flash",
                goal="Add automated refunds processing",
                test_status="passed",
            )
        )
        locks.release("billing.py:refund_card", agent_id="agent-refunds")

        # Orchestrator merges both branches into main!
        print("\n8. Merging feature/payments into main...")
        repo.switch_branch("main")
        repo.merge_branches("feature/payments", message="Merge payments feature")

        print("9. Performing AST-aware 3-way merge of feature/refunds into main...")
        # In Git, this would cause a line conflict because both added code at the bottom of the file!
        # In Cognit, AST-aware merger detects distinct function symbols and merges seamlessly!
        merged_cp = repo.merge_branches("feature/refunds", message="Merge refunds feature")
        print(f"   Merge Checkpoint ID: {merged_cp.id[:8]}")
        print(f"   Merge Status:        {merged_cp.agent_metadata.test_status}")

        final_content = billing_file.read_text(encoding="utf-8")
        print("\n10. Final Merged Code in billing.py:")
        print("--------------------------------------------------")
        print(final_content.strip())
        print("--------------------------------------------------")

        assert "def charge_card" in final_content
        assert "def refund_card" in final_content
        assert "def calculate_subtotal" in final_content
        print("\n[OK] Swarm simulation verified: Both functions merged cleanly with ZERO conflict!")


if __name__ == "__main__":
    run_swarm_simulation()
