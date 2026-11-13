"""Addition 2 pool: completeness/stability phrases only (Amendment 1 point 4)."""
import csv, hashlib, re, collections
def norm(s): return re.sub(r"[-_.]+","-",s).lower()
anchors="request node-uuid left-pad express uuid moment pycrypto nose six".split()
plan_npm="request-promise request-promise-native node-sass tslint babel-eslint istanbul phantomjs-prebuilt protractor karma coffee-script jade gulp-util uglify-es optimist nomnom querystring bower har-validator popper.js domexception abab sourcemap-codec inherits once wrappy isarray escape-html ee-first ms safe-buffer balanced-match concat-map array-flatten on-finished fresh depd unpipe bluebird q gulp grunt underscore react typescript lodash vite eslint axios zod prettier webpack chalk commander jest path-is-absolute is-number inflight mkdirp xmldom object-assign faker event-stream".split()
plan_py="theano pep8 sklearn distribute pytest-runner django-rest-swagger nose-parameterized flask-script flask-restplus oauth2 typed-ast asynctest fabric3 toml enum34 futures dataclasses contextlib2 webencodings ply singledispatch backports.functools-lru-cache appdirs requests django flask numpy pandas fastapi pydantic pytest httpx sqlalchemy black attrs python-dateutil docopt eventlet python-memcached chardet pyyaml pycurl m2crypto mock nose2 pytz simplejson argparse idna unittest2 ordereddict ipaddress pathlib funcsigs".split()
excluded={("npm",n) for n in anchors+plan_npm}|{("pypi",norm(n)) for n in anchors+plan_py}
owners=collections.Counter()
for r in csv.DictReader(open("../addition1/pools.tsv"),delimiter="\t"):
    excluded.add((r["ecosystem"],r["name"])); owners[r["repo"].split("/")[0].lower()]+=1
queries={r[0]:(r[1],r[2]) for r in csv.reader(open("raw/queries.tsv"),delimiter="\t")}
rows={}
for q,repo,eco,name,ver in csv.reader(open("raw/mapped.tsv"),delimiter="\t"):
    key=(eco,name if eco=="npm" else norm(name))
    if key in excluded or key in rows: continue
    rows[key]=dict(eco=eco,name=key[1],repo=repo,src=f"{queries[q][0]} [{queries[q][1]}]")
h=lambda r: hashlib.sha256(f"{r['eco']}:{r['name']}".encode()).hexdigest()
out=[]
for r in sorted(rows.values(),key=h):
    o=r["repo"].split("/")[0].lower()
    if owners[o]>=3: continue
    owners[o]+=1; out.append(r)
with open("pool.tsv","w") as f:
    f.write("rank\tecosystem\tname\tsource_query\trepo\tsha256_prefix\n")
    for i,r in enumerate(out,1): f.write(f"{i}\t{r['eco']}\t{r['name']}\t{r['src']}\t{r['repo']}\t{h(r)[:12]}\n")
print("pool",len(out),dict(collections.Counter(r["eco"] for r in out)))
