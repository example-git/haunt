import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

env=dict(os.environ,PGPASSWORD=Path('/data/database-password').read_text().strip())
def sql(query):
    p=subprocess.run(['psql','-h','127.0.0.1','-U','haunt_sync','-d','haunt_sync','-X','-At','-v','ON_ERROR_STOP=1','-c',query],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if p.returncode: raise RuntimeError('State query failed')
    return p.stdout.strip()
result={}
for table,removed,order in [('configuration',None,'singleton'),('accounts','vault_sequence','id'),('vaults','change_sequence','account_id,scope')]:
    value='to_jsonb(t)'+(" - '"+removed+"'" if removed else '')
    data=sql('SELECT coalesce(jsonb_agg('+value+' ORDER BY '+order+"),'[]'::jsonb)::text FROM haunt_sync."+table+' t')
    result[table]={'rows':len(json.loads(data)),'sha256':hashlib.sha256(data).hexdigest()}
result['saved_password_sha256']=hashlib.sha256(Path('/data/database-password').read_bytes()).hexdigest()
for route in ['healthz','v1/config']:
    with urllib.request.urlopen('http://127.0.0.1:8090/'+route,timeout=5) as response: result[route]=json.load(response)
result['version']=subprocess.check_output(['/usr/local/bin/haunt-sync','--version'],stderr=subprocess.STDOUT,text=True).strip().split()[-1]
print(json.dumps(result,indent=2))
