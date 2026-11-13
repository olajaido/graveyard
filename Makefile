.PHONY: eval eval-merge eval-still-works eval-versions
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
