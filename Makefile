.PHONY: eval eval-merge eval-analysis eval-still-works eval-versions eval-verify eval-apply-review eval-heldout eval-compare heldout-order
eval:
	cd backend && uv run python -m eval

eval-merge:
	cd backend && uv run python -m eval merge $(ARGS)

# Read-only v1 failure analysis; writes eval/analysis/v1-failures.{json,md}; add ARGS=--all for every row.
eval-analysis:
	cd backend && uv run python -m eval analysis $(ARGS)

# Needs Docker; installs only inside throwaway containers (T14 review check).
eval-still-works:
	python3 scripts/check_still_works.py $(ARGS)

# Read-only GETs to pypi.org and registry.npmjs.org from the host (Amendment 4.4).
eval-versions:
	python3 scripts/check_versions.py $(ARGS)

# Read-only HTTPS GETs to each row's evidence_url; checks the quote appears (T14 review).
eval-verify:
	python3 scripts/verify_evidence.py $(ARGS)

# Applies eval/review/decisions.tsv to the labelled set; add ARGS=--mark-reviewed to set reviewed=true (T14).
eval-apply-review:
	python3 scripts/apply_review.py $(ARGS)

# Held-out run, exclusive create of eval/heldout/results.<model>.json; pass ARGS="--model v1" or "--model v2".
eval-heldout:
	cd backend && uv run python -m eval --dataset heldout $(ARGS)

# Descriptive v1 to v2 transition table; writes eval/heldout/comparison.{json,md}; not a model run.
eval-compare:
	cd backend && uv run python -m eval compare

# Checks every heldout tag that exists against the order rules (design 13).
heldout-order:
	python3 scripts/check_heldout_order.py --verify-all
