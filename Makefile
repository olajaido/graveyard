.PHONY: eval eval-merge
eval:
	cd backend && uv run python -m eval

eval-merge:
	cd backend && uv run python -m eval merge $(ARGS)
