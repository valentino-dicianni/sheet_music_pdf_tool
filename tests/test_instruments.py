import pytest

from sheetmusic.parts.instruments import normalize_instrument, same_instrument


@pytest.mark.parametrize("ocr, expected", [
    ("3> TRUMPET 2", "Bb Trumpet 2"),
    ("F HORN I", "F Horn 1"),
    ("ASSOON", "Bassoon"),                       # clipped letters
    ("F Hom II", "F Horn 2"),                    # 'rn' read as 'm'
    ("Flute If", "Flute 2"),                     # OCR garbles of the numeral II
    ("Bb Clarinet U", "Bb Clarinet 2"),
    ("Trambone Ul", "Trombone 3"),
    ("Eb Alto Saxophone II", "Eb Alto Saxophone 2"),
    ("Bb Euphonium 6", "Bb Euphonium"),          # a clef glyph read as a digit is not a part number
    ("Hoorn 1 Eb", "Eb Hoorn 1"),                # transposition goes first
    ("Oboe ARCHIVOCUCOSAX Orient Express", "Oboe"),
])
def test_normalize_instrument(ocr, expected):
    assert normalize_instrument(ocr) == expected


def test_same_instrument():
    assert same_instrument("Bb Clarinet 2", "Clarinet 2")        # transposition does not matter
    assert not same_instrument("Flute 1", "Flute 2")             # part numbers do
    assert not same_instrument("Trumpet", "Trombone")
