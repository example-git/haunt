#!/usr/bin/env python3
"""Run only a disposable sync instance against the verified isolated fixture."""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time

DOCKER = ["docker", "--host=unix:///var/run/docker.sock"]
def run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs)
def main():
    parser=argparse.ArgumentParser();parser.add_argument("image");parser.add_argument("--client",required=True);args=parser.parse_args()
    info=json.loads(run(DOCKER+["inspect","chatxo-identity-check"]).stdout)[0]
    if info["Name"]!="/chatxo-identity-check" or info["Config"]["Image"]!="postgres:16-alpine" or info["NetworkSettings"]["Ports"]["5432/tcp"] != [{"HostIp":"127.0.0.1","HostPort":"32768"}]: raise RuntimeError("The isolated database identity does not match")
    database=os.environ["HAUNT_SYNC_TEST_DATABASE_URL"]
    if "@127.0.0.1:32768/haunt_sync_iteration" not in database: raise RuntimeError("The sync fixture database is required")
    with socket.socket() as sock:sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
    issuer=f"https://127.0.0.1:{port}";name="haunt-sync-check-"+secrets.token_hex(6);schema="sync_container_"+secrets.token_hex(6)
    with tempfile.TemporaryDirectory(prefix="haunt-sync-cert-") as directory:
        root=Path(directory);root.chmod(0o755)
        run(["openssl","req","-x509","-newkey","ec","-pkeyopt","ec_paramgen_curve:P-256","-nodes","-keyout",str(root/"key.pem"),"-out",str(root/"cert.pem"),"-days","1","-subj","/CN=127.0.0.1","-addext","subjectAltName=IP:127.0.0.1"])
        # These are synthetic one-day fixture certificates, never deployment keys.
        (root/"key.pem").chmod(0o644);(root/"cert.pem").chmod(0o644)
        envfile=root/"fixture.env";envfile.write_text("\n".join(["HAUNT_SYNC_DATABASE_URL="+database,"HAUNT_SYNC_ISSUER="+issuer,"HAUNT_SYNC_SCHEMA="+schema,"HAUNT_SYNC_LISTEN_ADDR=127.0.0.1:"+str(port),"HAUNT_SYNC_TLS_CERT=/tls/cert.pem","HAUNT_SYNC_TLS_KEY=/tls/key.pem"])+"\n");envfile.chmod(0o600)
        run(DOCKER+["run","-d","--entrypoint","/usr/local/bin/haunt-sync","--name",name,"--network","host","--read-only","--cap-drop","ALL","--security-opt","no-new-privileges:true","--env-file",str(envfile),"--mount","type=bind,src="+directory+",dst=/tls,readonly",args.image])
        control=root/"control.json";control.write_text(json.dumps({"name":name,"issuer":issuer,"schema":schema}));control.chmod(0o600)
        environment=os.environ.copy();environment.update({"NODE_EXTRA_CA_CERTS":str(root/"cert.pem"),"HAUNT_SYNC_CONTAINER_CONTROL":str(control),"HAUNT_SYNC_CONTAINER_ISSUER":issuer})
        for variable in ["DOCKER_HOST","DOCKER_CONTEXT","DOCKER_TLS","DOCKER_TLS_VERIFY","DOCKER_CERT_PATH"]: environment.pop(variable,None)
        try:
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                ready=subprocess.run(["curl","--silent","--fail","--max-time","2","--cacert",str(root/"cert.pem"),issuer+"/healthz"],capture_output=True)
                if ready.returncode==0:break
                state=json.loads(run(DOCKER+["inspect",name]).stdout)[0]["State"]
                if not state["Running"]:
                    diagnostic=subprocess.run(DOCKER+["logs","--tail","30",name],capture_output=True,text=True)
                    print(diagnostic.stdout);print(diagnostic.stderr)
                    raise RuntimeError("Disposable TLS sync process exited before readiness")
                time.sleep(.25)
            else:
                diagnostic=subprocess.run(DOCKER+["logs","--tail","30",name],capture_output=True,text=True)
                print(diagnostic.stdout);print(diagnostic.stderr)
                raise RuntimeError("Disposable TLS sync container did not become ready within its initialization budget")
            command=subprocess.run(["npm","exec","--","vitest","run","tests/sync-container.test.ts","--maxWorkers=1"],cwd=args.client,env=environment,capture_output=True,text=True)
            print(command.stdout);print(command.stderr)
            if command.returncode:raise RuntimeError("Production container protocol check failed")
            inspect=json.loads(run(DOCKER+["inspect",name]).stdout)[0]
            if inspect["Config"]["User"]!="65532:65532":raise RuntimeError("Sync process is not using the unprivileged image identity")
            print("PASS: standalone TLS binary path inside image, encrypted backup and restart restore")
        finally:
            subprocess.run(DOCKER+["stop","-t","60",name],capture_output=True)
            subprocess.run(DOCKER+["rm","-v",name],capture_output=True)
            # Drop only this run's schema, through the isolated fixture's own role.
            user=next((value.split("=",1)[1] for value in info["Config"]["Env"] if value.startswith("POSTGRES_USER=")),"postgres")
            run(DOCKER+["exec","chatxo-identity-check","psql","-U",user,"-d","haunt_sync_iteration","-c",'DROP SCHEMA IF EXISTS "'+schema+'" CASCADE'])
if __name__=="__main__":main()
