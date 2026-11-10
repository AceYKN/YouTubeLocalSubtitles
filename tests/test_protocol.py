import math

import pytest

from server.protocol import HEADER, decode_audio


def packet(**updates):
    values = dict(magic=b'YTLS', generation=3, sequence=7, media=40.5, rate=1.5, count=2)
    values.update(updates)
    return HEADER.pack(*values.values()) + b'\x00\x80\xff\x7f'


def test_js_wire_contract():
    frame = decode_audio(packet())
    assert frame.generation == 3 and frame.sequence == 7
    assert frame.media_start == 40.5 and frame.rate == 1.5
    assert frame.samples[0] == -1
    assert frame.samples[1] == pytest.approx(32767 / 32768)


@pytest.mark.parametrize('updates', [dict(media=math.nan), dict(rate=math.inf), dict(rate=0), dict(count=3201), dict(count=1), dict(generation=0), dict(magic=b'BAD!')])
def test_rejects_bad_audio(updates):
    with pytest.raises(ValueError):
        decode_audio(packet(**updates))
