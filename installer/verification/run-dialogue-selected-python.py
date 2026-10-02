"""Focused regressions and real mainloops in the user's selected interpreter."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'installer/verification'


def main():
    selected=sys.argv[1]
    env=dict(os.environ,PYTHONPATH=os.pathsep.join((str(ROOT/'ai'),str(ROOT/'ai/tests'))),PYTHONIOENCODING='utf-8')
    with tempfile.TemporaryDirectory(prefix='praat-dialogue-selected-') as directory:
        script='''
import os,sys,unittest
from pathlib import Path
from praat_ai import chat
fixture=Path(sys.argv[1]); runtime=fixture/'runtime'; runtime.mkdir()
config=fixture/'config.json'; config.write_text('{}')
os.environ['PRAAT_AI_CONFIG_PATH']=str(config)
chat.runtime_dir=lambda:runtime
names=['test_dialogue_fastpath','test_dialogue_stream','test_dialogue_ui',
       'test_dialogue_protocol','test_dialogue_measurement','test_api_capability_status','test_chat_process_fold']
suite=unittest.defaultTestLoader.loadTestsFromNames(names)
sys.exit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
'''
        cases=[('tests',[selected,'-c',script,directory]),
               ('live',[selected,str(OUT/'verify-dialogue-fastpath-live.py')]),
               ('api-live',[selected,str(OUT/'verify-api-capability-status-live.py')])]
        result={}
        for name,command in cases:
            log=OUT/f'dialogue-fastpath-selected-{name}.log'
            with log.open('wb') as stream:
                completed=subprocess.run(command,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
            result[name]=completed.returncode
            print(log.read_text(encoding='utf-8',errors='replace')[-1200:])
        (OUT/'dialogue-fastpath-selected-result.json').write_text(json.dumps(
            {'interpreter':selected,'exit_codes':result},indent=2),encoding='utf-8')
        return int(any(result.values()))


if __name__=='__main__':sys.exit(main())
