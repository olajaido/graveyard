.PHONY: eval eval-merge eval-still-works
eval:
	cd backend && uv run python -m eval

eval-merge:
	cd backend && uv run python -m eval merge $(ARGS)

# Needs Docker; installs only inside throwaway containers (T14 review check).
eval-still-works:
	python3 scripts/check_still_works.py $(ARGS)
