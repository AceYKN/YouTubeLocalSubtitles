import numpy as np
import soundfile as sf

from server.media import AudioReader


def test_media_seek_and_contiguous_reads_preserve_timestamps(tmp_path):
    rate=16000
    samples=(0.2*np.sin(np.arange(rate*14)*2*np.pi*317/rate)).astype(np.float32)
    path=tmp_path/'audio.wav';sf.write(path,samples,rate,subtype='FLOAT')
    reader=AudioReader('abcdefghijk',local_file=path)
    try:
        timestamp,first=reader.read(3,4)
        assert abs(timestamp-3)<1/rate
        np.testing.assert_allclose(first,samples[3*rate:7*rate],atol=1e-6)
        timestamp,following=reader.read(7,4)
        assert abs(timestamp-7)<1/rate
        np.testing.assert_allclose(following,samples[7*rate:11*rate],atol=1e-6)
        timestamp,rewind=reader.read(1.5,1)
        assert abs(timestamp-1.5)<1/rate
        np.testing.assert_allclose(rewind,samples[int(1.5*rate):int(2.5*rate)],atol=1e-6)
    finally:reader.close()
