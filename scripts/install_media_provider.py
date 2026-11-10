"""Install a pinned local playback-attestation helper; no Docker or home files."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
COMMIT='26475e9d3665b972c4aeb83b4dbaafcf64b88438'
DIGEST='9fd5acfeaa3b876c8046b307c4f862272a3c3aa59152d00f410b022dddda8b58'


def main():
    provider=ROOT/'runtime/bgutil';server=provider/'server'
    version_file=server/'src/utils.ts'
    built=server/'build/generate_once.js'
    if built.exists() and version_file.exists() and 'VERSION = "2.0.2"' in version_file.read_text(encoding='utf8'):
        print('Local media helper 2.0.2 already installed.')
        return
    archive=ROOT/'cache/bgutil-source-26475e9.zip'
    archive.parent.mkdir(parents=True,exist_ok=True)
    if not archive.exists():
        temporary=archive.with_suffix('.part')
        with urllib.request.urlopen(f'https://codeload.github.com/Brainicism/bgutil-ytdlp-pot-provider/zip/{COMMIT}',timeout=60) as source,temporary.open('wb') as output:
            shutil.copyfileobj(source,output)
        temporary.replace(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=DIGEST:
        raise ValueError('Media helper source checksum mismatch')
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            parts=Path(entry.filename).parts[1:]
            if not parts or (parts[0]!='server' and parts[0] not in ('LICENSE','README.md')):continue
            target=provider.joinpath(*parts).resolve()
            if not target.is_relative_to(provider.resolve()):raise ValueError('Invalid archive path')
            if entry.is_dir():target.mkdir(parents=True,exist_ok=True)
            else:target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read(entry))
    env=dict(os.environ,npm_config_cache=str(ROOT/'cache/npm'),XDG_CACHE_HOME=str(ROOT/'cache'))
    flags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0
    subprocess.run([shutil.which('npm.cmd') or 'npm','ci','--no-audit','--no-fund'],cwd=server,env=env,check=True,creationflags=flags)
    subprocess.run(['node',str(server/'node_modules/typescript/bin/tsc'),'--project',str(server/'tsconfig.json')],cwd=server,env=env,check=True,creationflags=flags)
    (provider/'SOURCE_COMMIT').write_text(COMMIT+'\n',encoding='utf8')
    print('Local media helper installed and source verified.')


if __name__=='__main__':main()
