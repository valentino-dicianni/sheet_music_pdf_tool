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
    ("French Horns 2-4", "Horns 2-4"),           # one part for several players
    ("C String Bass A", "C String Bass"),        # a second key letter is noise
])
def test_normalize_instrument(ocr, expected):
    assert normalize_instrument(ocr) == expected


def test_same_instrument():
    assert same_instrument("Bb Clarinet 2", "Clarinet 2")        # transposition does not matter
    assert not same_instrument("Flute 1", "Flute 2")             # part numbers do
    assert not same_instrument("Trumpet", "Trombone")


@pytest.mark.parametrize("ocr, expected", [
    ("Frautín", "Frautin"), ("Frautas 1 e 2", "Frautas 1 & 2"), ("Trompas 1 e 2", "Trompas 1 & 2"),   # Galician
    ("Clarinetto Sib 1", "Clarinetto 1"), ("Hautbois", "Hautbois"), ("Posaune 2", "Posaune 2"),       # it / fr / de
    ("Hoorn 1 Eb", "Eb Hoorn 1"),                                                                    # nl
])
def test_instrument_names_in_other_languages(ocr, expected):
    assert normalize_instrument(ocr) == expected


@pytest.mark.parametrize("not_an_instrument", ["Latin", "Allegro vivo", "Grandioso", "Maestoso", "Moderato", "Andante", "Majestic"])
def test_tempo_and_rehearsal_words_are_not_instruments(not_an_instrument):
    assert normalize_instrument(not_an_instrument) == ""


def test_a_misread_one_before_e_2():
    assert normalize_instrument("Trompas e 2") == "Trompas 1 & 2"


def test_a_misread_key_letter():
    assert normalize_instrument("Fb Alto Sax: 2") == "Eb Alto Sax 2"
    assert normalize_instrument("F Horn 1") == "F Horn 1"          # a real F stays


@pytest.mark.parametrize("ocr, expected", [("Sax. Tenores", "Sax Tenores"), ("Sax. Altos 1 e 2", "Sax Altos 1 & 2"), ("Flutes 1-2", "Flutes 1-2")])
def test_plural_names_are_kept_as_printed(ocr, expected):
    assert normalize_instrument(ocr) == expected


@pytest.mark.parametrize("word_, is_instrument", [("Pinoc", False), ("Pinocho", False), ("Flute", True), ("Horn", True),
                                                  ("ASSOON", True), ("Clannet", True), ("3ARITONE", True)])
def test_short_words_are_matched_exactly_long_ones_tolerate_a_misread_letter(word_, is_instrument):
    from sheetmusic.parts.instruments import canonical
    assert (canonical(word_) is not None) is is_instrument


def test_a_misread_key_in_a_header_that_starts_with_title_words():
    assert normalize_instrument("PIRATES OF THE CARIBBEAN Fb Alto Sax: 2") == "Eb Alto Sax 2"
