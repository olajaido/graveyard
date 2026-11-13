import csv, hashlib, re, collections
def norm(s): return re.sub(r"[-_.]+","-",s).lower()
anchors="request node-uuid left-pad express uuid moment pycrypto nose six".split()
plan_npm="request-promise request-promise-native node-sass tslint babel-eslint istanbul phantomjs-prebuilt protractor karma coffee-script jade gulp-util uglify-es optimist nomnom querystring bower har-validator popper.js domexception abab sourcemap-codec inherits once wrappy isarray escape-html ee-first ms safe-buffer balanced-match concat-map array-flatten on-finished fresh depd unpipe bluebird q gulp grunt underscore react typescript lodash vite eslint axios zod prettier webpack chalk commander jest path-is-absolute is-number inflight mkdirp xmldom object-assign faker event-stream".split()
plan_py="theano pep8 sklearn distribute pytest-runner django-rest-swagger nose-parameterized flask-script flask-restplus oauth2 typed-ast asynctest fabric3 toml enum34 futures dataclasses contextlib2 webencodings ply singledispatch backports.functools-lru-cache appdirs requests django flask numpy pandas fastapi pydantic pytest httpx sqlalchemy black attrs python-dateutil docopt eventlet python-memcached chardet pyyaml pycurl m2crypto mock nose2 pytz simplejson argparse idna unittest2 ordereddict ipaddress pathlib funcsigs".split()
excluded={("npm",n) for n in anchors+plan_npm}|{("pypi",norm(n)) for n in anchors+plan_py}
src_of={"inactive":"badge:inactive","unsupported":"badge:unsupported","abandoned":"badge:abandoned","moved":"badge:moved",
 "phr21":"phrase:feature complete","phr22":"phrase:feature-complete","phr23":"phrase:looking for maintainers",
 "phr24":"phrase:maintainers wanted","phr25":"phrase:no longer maintained","phr27":"phrase:maintenance mode","phr5":"phrase:\"maintenance mode\"","phr41":"phrase:feature complete (rst)","phr42":"phrase:feature-complete (rst)","phr43":"phrase:feature complete (readme.md)","phr44":"phrase:considered stable","phr45":"phrase:considered done","phr46":"phrase:stable and complete","phr49":"phrase:no further development"}
pool_of={"badge:inactive":"F","phrase:feature complete (rst)":"F","phrase:feature-complete (rst)":"F","phrase:feature complete (readme.md)":"F","phrase:considered stable":"F","phrase:considered done":"F","phrase:stable and complete":"F","phrase:no further development":"F","phrase:feature complete":"F","phrase:feature-complete":"F",
 "badge:unsupported":"A","phrase:looking for maintainers":"A","phrase:maintainers wanted":"A","phrase:maintenance mode":"A","phrase:\"maintenance mode\"":"A",
 "badge:abandoned":"D","badge:moved":"D","phrase:no longer maintained":"D"}
rows={}
for f in ["raw/mapped_badges.tsv","raw/mapped_phrases.tsv","raw/mapped_phrases2.tsv"]:
    for st,repo,eco,name,ver in csv.reader(open(f),delimiter="\t"):
        if st not in src_of: continue
        src=src_of[st]; key=(eco,name if eco=="npm" else norm(name))
        if key in excluded: continue
        prio="FAD".index(pool_of[src])
        if key not in rows or prio<rows[key]["prio"]:
            rows[key]=dict(eco=eco,name=key[1],ver=ver,repo=repo,src=src,pool=pool_of[src],prio=prio)
h=lambda r: hashlib.sha256(f"{r['eco']}:{r['name']}".encode()).hexdigest()
# owner cap 3, applied in hash order within each pool
out=collections.defaultdict(list); owners=collections.Counter()
for pool in "FAD":
    for r in sorted([r for r in rows.values() if r["pool"]==pool], key=h):
        o=r["repo"].split("/")[0].lower()
        if owners[o]>=3: continue
        owners[o]+=1; out[pool].append(r)
quota={"F":None,"A":None,"D":None}
final=[]
for pool in "FAD":
    sel=out[pool] if quota[pool] is None else out[pool][:quota[pool]]
    final+=sel
    print(pool,"available",len(out[pool]),"selected",len(sel))
c=collections.Counter(r["eco"] for r in final); print("total",len(final),dict(c))
with open("addition1.tsv","w") as f:
    f.write("rank\tpool\tecosystem\tname\tsource_query\trepo\tsha256_prefix\n")
    rk=collections.Counter()
    for r in final:
        rk[r["pool"]]+=1; i=rk[r["pool"]]
        f.write(f"{i}\t{r['pool']}\t{r['eco']}\t{r['name']}\t{r['src']}\t{r['repo']}\t{h(r)[:12]}\n")
