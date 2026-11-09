"""Package URL (purl) parsing, formatting and cache keys; repo-URL normalisation.

Pure, I/O-free logic. Public API is re-exported here once the modules land
(see design section 3):

- ``package_key(purl)`` identifies a package across versions (autopsy cache key).
- ``repo_key(repo)`` identifies a GitHub repository (repo-level evidence key).
"""
