#!/usr/bin/env python3
"""Create protected Pages project before uploading only a prepared site directory."""
import argparse
import json
import os
import re
import secrets
import subprocess
import time
from pathlib import Path

import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--private-config", required=True, type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--verify-path", action="append", help="Site path to verify after upload (repeatable); defaults to the wiki build's files")
    args = parser.parse_args()
    root = args.directory.resolve()
    paths = args.verify_path or ["/","/style.css","/search.js","/search-index.json","/coverage.json","/source-inventory.json"]
    for path in paths:
        if not path.startswith("/") or (path != "/" and not (root / path.lstrip("/")).is_file()):
            raise SystemExit(f"Verification path is not a file of the prepared site: {path}; no upload performed")
    if not (root / "_worker.js").exists() or not (root / "_routes.json").exists():
        raise SystemExit("Prepared report must contain all-route authentication worker")
    protected_worker = Path(__file__).resolve().parents[1] / "instadna" / "web" / "_worker.js"
    if (root / "_worker.js").read_bytes() != protected_worker.read_bytes():
        raise SystemExit("Protected deployment requires the reviewed authentication worker; no upload performed")
    routes = json.loads((root / "_routes.json").read_text())
    if routes != {"version": 1, "include": ["/*"], "exclude": []}:
        raise SystemExit("Report must authenticate every route")
    # Matches the site builder's reviewed image/audio publication types.
    allowed = {".html", ".css", ".js", ".json", ".png", ".webp", ".mp3", ".wav"}
    for p in root.rglob("*"):
        if p.is_symlink() or (p.is_file() and (p.suffix not in allowed or p.name.startswith("."))):
            raise SystemExit(f"Disallowed publication artifact: {p.relative_to(root)}")
    config_path = args.private_config.resolve()
    if config_path.is_relative_to(root):
        raise SystemExit("Credentials cannot be stored inside the publication directory")
    if config_path.exists():
        config = json.loads(config_path.read_text())
        if config["project"] != args.project or config["account_id"] != args.account_id:
            raise SystemExit("Private configuration belongs to another project/account")
    else:
        config = {"project":args.project,"account_id":args.account_id,"username":"owner","password":secrets.token_urlsafe(27)}
        config_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd,"w") as f:
            json.dump(config,f,indent=2)
    api = f"https://api.cloudflare.com/client/v4/accounts/{args.account_id}/pages/projects"
    session = requests.Session()
    session.headers["Authorization"] = "Bearer " + os.environ["CLOUDFLARE_API_TOKEN"]
    env_vars = {"REPORT_USERNAME":{"type":"secret_text","value":config["username"]},
                "REPORT_PASSWORD":{"type":"secret_text","value":config["password"]}}
    settings = {"deployment_configs":{environment:{"env_vars":env_vars, "fail_open":False} for environment in ["production","preview"]}}
    lookup = session.get(api + "/" + args.project, timeout=30)
    if lookup.status_code == 404:
        response = session.post(api,json={"name":args.project,"production_branch":"main",**settings},timeout=30)
    else:
        lookup.raise_for_status()
        # This script is scoped to its dedicated report project, never a shared host.
        response = session.patch(api + "/" + args.project,json=settings,timeout=30)
    if not response.ok:
        # API errors explain actionable blockers (for example project quota).
        # Never dump a request body containing access credentials.
        errors = response.json().get("errors", [])
        messages = "; ".join(str(error.get("message", "Unknown error")) for error in errors)
        for secret in [config["username"], config["password"]]:
            messages = messages.replace(secret, "[redacted]")
        raise SystemExit(f"Cloudflare project configuration HTTP {response.status_code}: {messages}. No site uploaded.")
    if not response.json().get("success"):
        raise SystemExit("Cloudflare rejected report protection configuration")
    check = session.get(api + "/" + args.project,timeout=30).json()["result"]
    for environment in ["production","preview"]:
        if check["deployment_configs"][environment].get("fail_open") is not False:
            raise SystemExit(f"Pages {environment} must fail closed; no upload performed")
        variables = check["deployment_configs"][environment]["env_vars"]
        if any(variables.get(k,{}).get("type") != "secret_text" for k in env_vars):
            raise SystemExit(f"Missing protected {environment} bindings; no upload performed")
    # Copy no environment files into the prepared output; Wrangler receives only the inherited process environment.
    process = subprocess.run(["wrangler","pages","deploy",str(root),"--project-name",args.project,"--branch","main","--commit-dirty=true"],
        env={**os.environ,"CLOUDFLARE_ACCOUNT_ID":args.account_id},text=True,capture_output=True)
    print(process.stdout)
    if process.returncode:
        print(process.stderr)
        raise SystemExit(process.returncode)
    match = re.findall(r'https://[a-zA-Z0-9-]+\.' + re.escape(args.project) + r'\.pages\.dev',process.stdout)
    if not match:
        raise SystemExit("Deployment finished but its immutable URL was not returned; verify manually")
    deployment = match[-1]
    config["url"] = f"https://{args.project}.pages.dev"
    config["deployment_urls"] = sorted(set(config.get("deployment_urls",[]) + [deployment]))
    config_path.write_text(json.dumps(config,indent=2)+"\n")
    config_path.chmod(0o600)
    outcomes = []
    # Production deployments do not automatically have a `main` branch alias.
    # Verify only aliases returned by Pages, never a guessed hostname.
    deployments = session.get(api + "/" + args.project + "/deployments", timeout=30)
    deployments.raise_for_status()
    deployed = next((d for d in deployments.json()["result"] if d["url"] == deployment), None)
    if deployed is None:
        raise SystemExit("New deployment missing from Pages API; verify manually")
    urls = list(dict.fromkeys([config["url"], deployment, *(deployed.get("aliases") or [])]))
    for base in urls:
        for path in paths:
            for attempt in range(5):
                try:
                    unauth = requests.get(base+path,timeout=30)
                    auth = requests.get(base+path,auth=(config["username"],config["password"]),timeout=30)
                except requests.RequestException:
                    if attempt == 4:
                        raise SystemExit(f"Deployment created, but HTTPS verification is unavailable: {base+path}. Retry verification; do not redeploy.")
                    time.sleep(2)
                    continue
                if unauth.status_code==401 and auth.status_code==200:
                    break
                time.sleep(2)
            if unauth.status_code != 401 or auth.status_code != 200:
                raise SystemExit(f"Protection verification failed: {base+path}, unauth={unauth.status_code}, auth={auth.status_code}")
            if "no-store" not in auth.headers.get("Cache-Control",""):
                raise SystemExit("Authenticated content lacks no-store protection")
            outcomes.append({"url":base+path,"anonymous":unauth.status_code,"authenticated":auth.status_code,"no_store":True})
    config["verification"] = outcomes
    config_path.write_text(json.dumps(config,indent=2)+"\n")
    print(f"Verified {len(outcomes)} protected URLs. Production: {config['url']}")


if __name__ == "__main__":
    main()
