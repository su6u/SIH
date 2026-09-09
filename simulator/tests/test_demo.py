from swarmroute.demo import run_consensus_demo, run_demo


def test_demo_is_deterministic_and_commits_a_safe_winner() -> None:
    first = run_demo(seed=7)
    second = run_demo(seed=7)

    assert first == second
    assert first["winner"] in {"R1", "R2", "R3"}
    assert first["reservations"]["vertices"] > 0
    assert first["reservations"]["edges"] > 0


def test_consensus_demo_converges_and_partition_demo_withholds_claims() -> None:
    healthy = run_consensus_demo()
    partitioned = run_consensus_demo(partition=True)

    assert {state["claim_candidate"] for state in healthy["replicas"].values()} == {
        "R2"
    }
    assert all(
        state["claim_candidate"] is None for state in partitioned["replicas"].values()
    )
