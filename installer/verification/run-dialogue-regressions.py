"""Run unchanged suites with private fixtures writable by Low-integrity Praat."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'installer/verification'
RECORDS=ROOT/'test-records/installer'
LOW=Path(os.environ['USERPROFILE'])/'AppData/LocalLow/Praat/verification'
LOW.mkdir(parents=True,exist_ok=True)


def main():
    env=dict(os.environ,PYTHONPATH=str(ROOT/'ai'),PYTHONIOENCODING='utf-8')
    with tempfile.TemporaryDirectory(prefix='dialogue-',dir=LOW) as directory:
        env.update(TEMP=directory,TMP=directory)
        # The .NET Framework test host failed before Main from the Unicode
        # checkout path on this host. Run the exact compiled bytes in an ASCII
        # temporary path; installation contract cases still use Chinese paths.
        host=Path(directory)/'ContractTests.exe'
        shutil.copyfile(OUT/'ContractTests.exe',host)
        test_script='''
import os, sys, unittest
from pathlib import Path
from praat_ai import chat, config
fixture=Path(sys.argv[1]); runtime=fixture/'runtime'; runtime.mkdir()
private_config=fixture/'config.json'; private_config.write_text('{}')
chat.runtime_dir=lambda:runtime
os.environ['PRAAT_AI_CONFIG_PATH']=str(private_config)
suite=unittest.defaultTestLoader.discover('ai/tests')
sys.exit(not unittest.TextTestRunner().run(suite).wasSuccessful())
'''
        cases=[('contracts',[str(host),sys.executable,str(OUT/'python_without_deps/Scripts/python.exe')]),
               ('python',[sys.executable,'-c',test_script,directory])]
        results={}
        for name,command in cases:
            log=RECORDS/f'dialogue-fastpath-full-{name}.log'
            with log.open('wb') as stream:
                result=subprocess.run(command,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
            output=log.read_bytes()
            print(output.decode('utf-8',errors='replace')[-1600:])
            results[name]=result.returncode
        (RECORDS/'dialogue-fastpath-full-result.json').write_text(json.dumps(
            {'python':sys.version,'fixture_integrity_location':'LocalLow','exit_codes':results},indent=2),encoding='utf-8')
        return int(any(results.values()))


if __name__=='__main__':sys.exit(main())
