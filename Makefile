.PHONY: eval eval-merge eval-still-works eval-versions eval-verify eval-apply-review
eval:
	cd backend && uv run python -m eval

eval-merge:
	cd backend && uv run python -m eval merge $(ARGS)

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
