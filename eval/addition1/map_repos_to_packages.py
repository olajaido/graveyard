import json, sys, re, urllib.request, concurrent.futures as cf
def get(url):
    try:
        with urllib.request.urlopen(url, timeout=20) as r: return json.load(r)
    except Exception: return None
def norm(s): return re.sub(r"[-_.]+","-",s).lower()
def check(status, repo):
    owner, name = repo.split("/")
    key = f"github.com/{owner}/{name}".lower()
    out=[]
    for cand in {name.lower(), norm(name), name.lower().removeprefix("python-"), name.lower().removeprefix("py")} :
        p = get(f"https://pypi.org/pypi/{cand}/json")
        if p:
            info=p["info"]; blob=json.dumps([info.get("home_page"),info.get("project_urls"),info.get("download_url")]).lower()
            if key in blob: out.append(("pypi",norm(info["name"]),info["version"]))
        n = get(f"https://registry.npmjs.org/{cand}/latest")
        if n:
            blob=json.dumps([n.get("repository"),n.get("homepage"),n.get("bugs")]).lower()
            if key in blob and not n.get("name","").startswith("@"): out.append(("npm",n["name"],n["version"]))
    return [(status,repo)+o for o in set(out)]
jobs=[]
for s in sys.argv[1:]:
    for repo in open(f"raw/repos_{s}.txt").read().split():
        jobs.append((s,repo))
with cf.ThreadPoolExecutor(16) as ex:
    for res in ex.map(lambda j: check(*j), jobs):
        for r in res: print("\t".join(r))
