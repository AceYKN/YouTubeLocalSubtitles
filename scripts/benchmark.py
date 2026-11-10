"""Small real-model smoke benchmark, not a substitute for the PRD acceptance set."""
import asyncio
import json
import time

import soundfile as sf

from server.config import ROOT, ASR_NAME, load_config
from server.engine import Engine


async def main():
    engine=Engine(load_config())
    samples,rate=sf.read(ROOT/'models'/ASR_NAME/'test_wavs/rap1.wav',dtype='float32')
    assert rate==16000
    measurements=[]
    try:
        for start in [0,4,8]:
            chunk=samples[start*16000:(start+4)*16000]
            before=time.monotonic();result=await engine.recognize(chunk)
            measurements.append({'audio_seconds':len(chunk)/16000,'total_seconds':round(time.monotonic()-before,3),
                'inference_seconds':result['inference_seconds'],'language':result['language'],
                'characters':len(result['text'])})
        started=time.monotonic()
        translation=await engine.translator.translate('This video explains how to build a local speech recognition system without uploading your audio.',[])
        translation_seconds=round(time.monotonic()-started,3)
        started=time.monotonic()
        translation2=await engine.translator.translate('You can choose English, Chinese, or bilingual subtitles.',[])
        warm_seconds=round(time.monotonic()-started,3)
        result={'asr':measurements,'translation_cold_seconds':translation_seconds,'translation_warm_seconds':warm_seconds,
                'translation_examples':[translation,translation2]}
        folder=ROOT/'work';folder.mkdir(exist_ok=True)
        (folder/'benchmark.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False),flush=True)
    finally:
        await engine.close()


if __name__=='__main__':asyncio.run(main())
