import pytest

from conftest import warp_to

NOW = "2099-01-01T00:00:00Z"
DEADLINE = "2099-01-31T23:59:59Z"
AFTER_DEADLINE = "2099-02-01T00:00:00Z"

VALID_TWEET = "https://x.com/alice/status/1000000000000000001"
VALID_TWEET_2 = "https://x.com/alice/status/1000000000000000002"
VALID_PR = "https://github.com/octocat/hello-world/pull/42"
VALID_GENERIC = "https://example.com/proof/1"

VERIFIER_PROMPT_MARKER = r".*strict, impartial verifier for an on-chain bounty.*"


# --- helpers ---------------------------------------------------------------

def create_tweet_quest(contract, direct_vm, creator, max_winners=1, reward=100,
                        deadline="", must_include=""):
    direct_vm.sender = creator
    direct_vm.value = reward * max_winners
    contract.create_quest(
        "Tweet about us", "tweet", "Post praising the project", must_include,
        "", max_winners, reward, deadline,
    )
    direct_vm.value = 0


def create_pr_quest(contract, direct_vm, creator, max_winners=1, reward=100, deadline=""):
    direct_vm.sender = creator
    direct_vm.value = reward * max_winners
    contract.create_quest(
        "Fix a bug", "github_pr", "PR that fixes the reported bug", "",
        "", max_winners, reward, deadline,
    )
    direct_vm.value = 0


def create_generic_quest(contract, direct_vm, creator, max_winners=1, reward=100):
    direct_vm.sender = creator
    direct_vm.value = reward * max_winners
    contract.create_quest(
        "Write a blog post", "generic", "Post reviews the product favorably", "",
        "example.com", max_winners, reward, "",
    )
    direct_vm.value = 0


def mock_pass(direct_vm, code, keyword=None):
    direct_vm.clear_mocks()
    body = f"profile page. verification code: {code}."
    if keyword:
        body += f" {keyword}"
    direct_vm.mock_web(r".*", {"status": 200, "body": body})
    direct_vm.mock_llm(VERIFIER_PROMPT_MARKER, '{"passed": true}')


def mock_fail(direct_vm, code):
    direct_vm.clear_mocks()
    direct_vm.mock_web(r".*", {"status": 200, "body": f"irrelevant page. code: {code}."})
    direct_vm.mock_llm(VERIFIER_PROMPT_MARKER, '{"passed": false}')


def mock_missing_code(direct_vm):
    direct_vm.clear_mocks()
    direct_vm.mock_web(r".*", {"status": 200, "body": "a page with no code on it at all"})
    direct_vm.mock_llm(VERIFIER_PROMPT_MARKER, '{"passed": true}')


# --- quest creation ----------------------------------------------------------

def test_create_quest(contract, direct_vm, direct_bob):
    create_tweet_quest(contract, direct_vm, direct_bob, max_winners=2, reward=100)
    q = contract.get_quest(0)
    assert q["creator"] == str(direct_bob)
    assert q["kind"] == "tweet"
    assert q["max_winners"] == 2
    assert q["escrow"] == "200"
    assert q["closed"] is False


def test_create_quest_rejects_wrong_deposit(contract, direct_vm, direct_bob):
    direct_vm.sender = direct_bob
    direct_vm.value = 50  # should be 200
    with pytest.raises(Exception):
        contract.create_quest("T", "tweet", "criteria", "", "", 2, 100, "")
    direct_vm.value = 0


def test_create_quest_rejects_invalid_kind(contract, direct_vm, direct_bob):
    direct_vm.sender = direct_bob
    direct_vm.value = 100
    with pytest.raises(Exception):
        contract.create_quest("T", "reddit", "criteria", "", "", 1, 100, "")
    direct_vm.value = 0


def test_create_quest_rejects_missing_domain_for_generic(contract, direct_vm, direct_bob):
    direct_vm.sender = direct_bob
    direct_vm.value = 100
    with pytest.raises(Exception):
        contract.create_quest("T", "generic", "criteria", "", "", 1, 100, "")
    direct_vm.value = 0


def test_create_quest_rejects_too_many_winners(contract, direct_vm, direct_bob):
    direct_vm.sender = direct_bob
    direct_vm.value = 100 * 5000
    with pytest.raises(Exception):
        contract.create_quest("T", "tweet", "criteria", "", "", 5000, 100, "")
    direct_vm.value = 0


def test_create_quest_rejects_past_deadline(contract, direct_vm, direct_bob):
    warp_to(direct_vm, NOW)
    direct_vm.sender = direct_bob
    direct_vm.value = 100
    with pytest.raises(Exception):
        contract.create_quest("T", "tweet", "criteria", "", "", 1, 100, "2098-12-31T23:59:59Z")
    direct_vm.value = 0


def test_create_quest_rejects_malformed_deadline(contract, direct_vm, direct_bob):
    direct_vm.sender = direct_bob
    direct_vm.value = 100
    with pytest.raises(Exception):
        contract.create_quest("T", "tweet", "criteria", "", "", 1, 100, "not-a-date")
    direct_vm.value = 0


def test_create_quest_rejects_too_many_keywords(contract, direct_vm, direct_bob):
    direct_vm.sender = direct_bob
    direct_vm.value = 100
    with pytest.raises(Exception):
        contract.create_quest("T", "tweet", "criteria", "a,b,c,d,e,f", "", 1, 100, "")
    direct_vm.value = 0


def test_get_required_deposit(contract):
    assert contract.get_required_deposit(100, 3) == "300"


# --- submission: tweet happy / unhappy paths ---------------------------------

def test_submit_proof_pass_awards_reward(contract, direct_vm, direct_bob, direct_carol):
    create_tweet_quest(contract, direct_vm, direct_bob, max_winners=1, reward=100)
    code = contract.get_verification_code(0, direct_carol)
    mock_pass(direct_vm, code)
    direct_vm.sender = direct_carol
    contract.submit_proof(0, VALID_TWEET)
    assert contract.get_claimable(direct_carol) == "100"
    assert contract.get_submission_status(0, direct_carol) == "approved"
    q = contract.get_quest(0)
    assert q["winners"] == 1
    assert q["escrow"] == "0"
    # slots are full but the quest itself isn't auto-closed -- close_quest is a
    # separate, explicit action so a creator can still add_winners() to reopen it
    assert q["closed"] is False


def test_submit_proof_wrong_kind_url_rejected(contract, direct_vm, direct_bob, direct_carol):
    create_tweet_quest(contract, direct_vm, direct_bob)
    direct_vm.sender = direct_carol
    with pytest.raises(Exception):
        contract.submit_proof(0, VALID_PR)  # github URL on a tweet quest


def test_submit_proof_missing_code_fails_without_llm_override(contract, direct_vm, direct_bob, direct_carol):
    create_tweet_quest(contract, direct_vm, direct_bob)
    mock_missing_code(direct_vm)  # LLM says "passed" but the wallet code is absent
    direct_vm.sender = direct_carol
    contract.submit_proof(0, VALID_TWEET)
    assert contract.get_submission_status(0, direct_carol) == "rejected"
    assert contract.get_claimable(direct_carol) == "0"


def test_submit_proof_llm_rejects(contract, direct_vm, direct_bob, direct_carol):
    create_tweet_quest(contract, direct_vm, direct_bob)
    code = contract.get_verification_code(0, direct_carol)
    mock_fail(direct_vm, code)
    direct_vm.sender = direct_carol
    contract.submit_proof(0, VALID_TWEET)
    assert contract.get_submission_status(0, direct_carol) == "rejected"
    assert contract.get_attempts_left(0, direct_carol) == "2"


def test_submit_proof_required_keyword_enforced(contract, direct_vm, direct_bob, direct_carol):
    create_tweet_quest(contract, direct_vm, direct_bob, must_include="#genlayer")
    code = contract.get_verification_code(0, direct_carol)
    mock_pass(direct_vm, code)  # page has code but not the hashtag
    direct_vm.sender = direct_carol
    contract.submit_proof(0, VALID_TWEET)
    assert contract.get_submission_status(0, direct_carol) == "rejected"


def test_submit_proof_required_keyword_present_passes(contract, direct_vm, direct_bob, direct_carol):
    create_tweet_quest(contract, direct_vm, direct_bob, must_include="#genlayer")
    code = contract.get_verification_code(0, direct_carol)
    mock_pass(direct_vm, code, keyword="#genlayer")
    direct_vm.sender = direct_carol
    contract.submit_proof(0, VALID_TWEET)
    assert contract.get_submission_status(0, direct_carol) == "approved"


def test_submit_proof_duplicate_url_rejected(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    create_tweet_quest(contract, direct_vm, direct_bob, max_winners=2, reward=100)
    code_carol = contract.get_verification_code(0, direct_carol)
    mock_pass(direct_vm, code_carol)
    direct_vm.sender = direct_carol
    contract.submit_proof(0, VALID_TWEET)

    code_dave = contract.get_verification_code(0, direct_dave)
    mock_pass(direct_vm, code_dave)  # page still only carries carol's code, not dave's
    direct_vm.sender = direct_dave
    with pytest.raises(Exception):
        contract.submit_proof(0, VALID_TWEET)  # same tweet id already used


def test_submit_proof_after_reward_slots_exhausted(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    create_tweet_quest(contract, direct_vm, direct_bob, max_winners=1, reward=100)
    code = contract.get_verification_code(0, direct_carol)
    mock_pass(direct_vm, code)
    direct_vm.sender = direct_carol
    contract.submit_proof(0, VALID_TWEET)

    direct_vm.sender = direct_dave
    with pytest.raises(Exception):
        contract.submit_proof(0, VALID_TWEET_2)


def test_submit_proof_rejects_after_deadline(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    create_tweet_quest(contract, direct_vm, direct_bob, deadline=DEADLINE)
    warp_to(direct_vm, AFTER_DEADLINE)
    code = contract.get_verification_code(0, direct_carol)
    mock_pass(direct_vm, code)
    direct_vm.sender = direct_carol
    with pytest.raises(Exception):
        contract.submit_proof(0, VALID_TWEET)


def test_submit_proof_max_attempts_then_requires_appeal(contract, direct_vm, direct_bob, direct_carol):
    create_tweet_quest(contract, direct_vm, direct_bob)
    code = contract.get_verification_code(0, direct_carol)
    for _ in range(3):
        mock_fail(direct_vm, code)
        direct_vm.sender = direct_carol
        contract.submit_proof(0, VALID_TWEET)
    assert contract.get_attempts_left(0, direct_carol) == "0"
    mock_pass(direct_vm, code)
    direct_vm.sender = direct_carol
    with pytest.raises(Exception):
        contract.submit_proof(0, VALID_TWEET)  # attempts exhausted, must use appeal()


# --- github_pr and generic kinds --------------------------------------------

def test_submit_proof_github_pr_happy_path(contract, direct_vm, direct_bob, direct_carol):
    create_pr_quest(contract, direct_vm, direct_bob)
    code = contract.get_verification_code(0, direct_carol)
    mock_pass(direct_vm, code)
    direct_vm.sender = direct_carol
    contract.submit_proof(0, VALID_PR)
    assert contract.get_submission_status(0, direct_carol) == "approved"


def test_submit_proof_github_pr_rejects_non_pull_url(contract, direct_vm, direct_bob, direct_carol):
    create_pr_quest(contract, direct_vm, direct_bob)
    direct_vm.sender = direct_carol
    with pytest.raises(Exception):
        contract.submit_proof(0, "https://github.com/octocat/hello-world/issues/1")


def test_submit_proof_generic_happy_path(contract, direct_vm, direct_bob, direct_carol):
    create_generic_quest(contract, direct_vm, direct_bob)
    code = contract.get_verification_code(0, direct_carol)
    mock_pass(direct_vm, code)
    direct_vm.sender = direct_carol
    contract.submit_proof(0, VALID_GENERIC)
    assert contract.get_submission_status(0, direct_carol) == "approved"


def test_submit_proof_generic_rejects_wrong_domain(contract, direct_vm, direct_bob, direct_carol):
    create_generic_quest(contract, direct_vm, direct_bob)
    direct_vm.sender = direct_carol
    with pytest.raises(Exception):
        contract.submit_proof(0, "https://not-example.com/proof/1")


# --- appeals -----------------------------------------------------------------

def test_appeal_flow_approved_by_moderator(contract, direct_vm, direct_bob, direct_carol, direct_alice):
    create_tweet_quest(contract, direct_vm, direct_bob)
    code = contract.get_verification_code(0, direct_carol)
    mock_fail(direct_vm, code)
    direct_vm.sender = direct_carol
    contract.submit_proof(0, VALID_TWEET)

    direct_vm.sender = direct_carol
    contract.appeal(0, VALID_TWEET, "The bot misread my tweet, please check manually.")
    assert contract.get_submission_status(0, direct_carol) == "appeal_pending"

    direct_vm.sender = direct_alice  # contract owner, also a moderator by default
    contract.resolve_appeal(0, direct_carol, True)
    assert contract.get_submission_status(0, direct_carol) == "approved"
    assert contract.get_claimable(direct_carol) == "100"


def test_appeal_reject_requires_moderator_not_creator(contract, direct_vm, direct_bob, direct_carol):
    create_tweet_quest(contract, direct_vm, direct_bob)
    code = contract.get_verification_code(0, direct_carol)
    mock_fail(direct_vm, code)
    direct_vm.sender = direct_carol
    contract.submit_proof(0, VALID_TWEET)
    direct_vm.sender = direct_carol
    contract.appeal(0, VALID_TWEET, "please review")

    direct_vm.sender = direct_bob  # creator, not a moderator
    with pytest.raises(Exception):
        contract.resolve_appeal(0, direct_carol, False)


def test_appeal_only_allowed_when_rejected(contract, direct_vm, direct_bob, direct_carol):
    create_tweet_quest(contract, direct_vm, direct_bob)
    direct_vm.sender = direct_carol
    with pytest.raises(Exception):
        contract.appeal(0, VALID_TWEET, "note")  # never submitted, nothing to appeal


# --- withdraw / escrow / close ------------------------------------------------

def test_withdraw_pulls_balance_and_zeroes_it(contract, direct_vm, direct_bob, direct_carol):
    create_tweet_quest(contract, direct_vm, direct_bob)
    code = contract.get_verification_code(0, direct_carol)
    mock_pass(direct_vm, code)
    direct_vm.sender = direct_carol
    contract.submit_proof(0, VALID_TWEET)
    contract.withdraw()
    assert contract.get_claimable(direct_carol) == "0"
    with pytest.raises(Exception):
        contract.withdraw()  # nothing left


def test_close_quest_refunds_unclaimed_escrow_to_creator(contract, direct_vm, direct_bob):
    create_tweet_quest(contract, direct_vm, direct_bob, max_winners=3, reward=100)
    direct_vm.sender = direct_bob
    contract.close_quest(0)
    assert contract.get_claimable(direct_bob) == "300"
    assert contract.get_quest(0)["closed"] is True


def test_close_quest_rejects_non_creator_non_moderator(contract, direct_vm, direct_bob, direct_carol):
    create_tweet_quest(contract, direct_vm, direct_bob)
    direct_vm.sender = direct_carol
    with pytest.raises(Exception):
        contract.close_quest(0)


def test_close_quest_blocked_while_appeal_pending(contract, direct_vm, direct_bob, direct_carol):
    create_tweet_quest(contract, direct_vm, direct_bob)
    code = contract.get_verification_code(0, direct_carol)
    mock_fail(direct_vm, code)
    direct_vm.sender = direct_carol
    contract.submit_proof(0, VALID_TWEET)
    direct_vm.sender = direct_carol
    contract.appeal(0, VALID_TWEET, "note")

    direct_vm.sender = direct_bob
    with pytest.raises(Exception):
        contract.close_quest(0)


def test_add_winners_tops_up_escrow(contract, direct_vm, direct_bob):
    create_tweet_quest(contract, direct_vm, direct_bob, max_winners=1, reward=100)
    direct_vm.sender = direct_bob
    direct_vm.value = 200
    contract.add_winners(0, 2)
    direct_vm.value = 0
    q = contract.get_quest(0)
    assert q["max_winners"] == 3
    assert q["escrow"] == "300"


def test_extend_deadline_cannot_go_backwards(contract, direct_vm, direct_bob):
    warp_to(direct_vm, NOW)
    create_tweet_quest(contract, direct_vm, direct_bob, deadline=DEADLINE)
    direct_vm.sender = direct_bob
    with pytest.raises(Exception):
        contract.extend_deadline(0, "2099-01-15T00:00:00Z")  # earlier than DEADLINE


def test_extend_deadline_forward_succeeds(contract, direct_vm, direct_bob):
    warp_to(direct_vm, NOW)
    create_tweet_quest(contract, direct_vm, direct_bob, deadline=DEADLINE)
    direct_vm.sender = direct_bob
    contract.extend_deadline(0, "2099-06-01T00:00:00Z")
    assert contract.get_quest(0)["deadline"] == "2099-06-01T00:00:00Z"


def test_set_quest_paused_blocks_submission(contract, direct_vm, direct_bob, direct_carol):
    create_tweet_quest(contract, direct_vm, direct_bob)
    direct_vm.sender = direct_bob
    contract.set_quest_paused(0, True)
    code = contract.get_verification_code(0, direct_carol)
    mock_pass(direct_vm, code)
    direct_vm.sender = direct_carol
    with pytest.raises(Exception):
        contract.submit_proof(0, VALID_TWEET)


# --- admin / governance -------------------------------------------------------

def test_global_pause_blocks_new_quests(contract, direct_vm, direct_alice, direct_bob):
    direct_vm.sender = direct_alice  # owner
    contract.set_global_pause(True)
    direct_vm.sender = direct_bob
    direct_vm.value = 100
    with pytest.raises(Exception):
        contract.create_quest("T", "tweet", "criteria", "", "", 1, 100, "")
    direct_vm.value = 0


def test_set_moderator_owner_only(contract, direct_vm, direct_bob, direct_carol):
    direct_vm.sender = direct_bob
    with pytest.raises(Exception):
        contract.set_moderator(direct_carol, True)


def test_ownership_transfer_two_step(contract, direct_vm, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    contract.propose_owner(direct_bob)
    direct_vm.sender = direct_bob
    contract.accept_ownership()
    assert contract.get_config()["owner"] == str(direct_bob)


def test_ownership_transfer_rejects_wrong_acceptor(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    direct_vm.sender = direct_alice
    contract.propose_owner(direct_bob)
    direct_vm.sender = direct_carol
    with pytest.raises(Exception):
        contract.accept_ownership()


def test_fee_is_credited_to_owner(contract_with_fee, direct_vm, direct_alice, direct_bob):
    direct_vm.sender = direct_bob
    total = 100
    fee = (total * 500) // 10000  # 5%
    direct_vm.value = total + fee
    contract_with_fee.create_quest("T", "tweet", "criteria", "", "", 1, 100, "")
    direct_vm.value = 0
    assert contract_with_fee.get_claimable(direct_alice) == str(fee)


# --- views ---------------------------------------------------------------

def test_get_open_quests_excludes_closed(contract, direct_vm, direct_bob):
    create_tweet_quest(contract, direct_vm, direct_bob)
    create_tweet_quest(contract, direct_vm, direct_bob)
    direct_vm.sender = direct_bob
    contract.close_quest(0)
    open_quests = contract.get_open_quests(0, 10)
    ids = [q["id"] for q in open_quests["items"]]
    assert 0 not in ids
    assert 1 in ids


def test_get_user_stats_after_award(contract, direct_vm, direct_bob, direct_carol):
    create_tweet_quest(contract, direct_vm, direct_bob, reward=150)
    code = contract.get_verification_code(0, direct_carol)
    mock_pass(direct_vm, code)
    direct_vm.sender = direct_carol
    contract.submit_proof(0, VALID_TWEET)
    stats = contract.get_user_stats(direct_carol)
    assert stats["completed"] == 1
    assert stats["total_earned"] == "150"
