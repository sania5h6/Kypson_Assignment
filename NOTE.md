# RFQ Parser – Note

## Approach
Rule-based, no model. Normalise the text first: lowercase it, strip Indian digit-group commas (`1,50,000`), fix typos with a fuzzy match against domain words (`cartoon → carton`, `strech → stretch`), and turn spoken numbers into digits (`do lakh`, `dedh lakh`, `paanch hazaar`). Then:
- **Category**: ordered keyword rules. The order handles the overlaps: jumbo/FIBC first, then BOPP, then woven/cement/AD Star, then pouch, then box/carton. A plain "box" ends up as corrugated_box.
- **Quantity**: every number is classified by the words around it:
  - spec numbers are dropped (gsm, mic, ply, `12x18`, inch, colour, price, phone).
  - weights directly before a bag word or "capacity/swl/wala" are fill weights and are ignored.
  - after that, priority is: explicit count (pcs/nos/bags) > bare number (for bags and boxes) > weight.
- **Location**: an offline GeoNames gazetteer (`geonamescache`, ~3,800 Indian towns plus their aliases such as Baroda and Bombay, large world cities, and countries). Ranking is city > country > state. An explicit "deliver to X" always wins, even if X is unknown. I chose a gazetteer over my own city list so it works on places I never wrote tests for.

## Score on my_tests.jsonl (62 examples)
`python score.py my_tests.jsonl` → **62/62 on every field, 100%**, in about 0.4 s including the gazetteer load. I wrote these tests myself, so this number is optimistic. I also ran about 40 extra messages, phrased differently and with new places, that are not in the file. They exposed real bugs, which I fixed with general rules rather than per-message patches: "approx"/"box" ending in `x` being read as a dimension, "50kg x 1 lakh", "2.5L pcs", and real cities like Kota on my stoplist.

## 3 messages it gets wrong
1. `25 kg bopp bag chahiye 1 truck load` → quantity 1, pcs. "Truck load" is not a unit I handle, so the lone "1" is taken as a count. The correct answer is unknown/None.
2. `shrink sleeve film 40 micron 500kg Daman and Diu` → location "Diu". The gazetteer matches at most 3 words and has "Diu" and "Daman" separately, so the last one wins.
3. `bopp bags 25 kg 50000 pcs aur 50 kg 30000 pcs, Nagpur` → 50000. Messages with several line items need a list output. The 6-key schema forces one answer, and I take the first count.

Known weak spots: I guess the unit when it is missing (a bare number means pcs for bags and boxes, kg for film). City names used as non-places ("Chennai Super Kings") are tagged as locations. "Non woven" and "carry bags" fall into woven_sack.

## With 1,000 real labelled examples
- First, sort the rule failures by field and pattern to see which rules break most.
- Then train a small token tagger, either a CRF or a fine-tuned DistilBERT/IndicBERT, to tag the QTY, FILL_WEIGHT, GSM, MICRON and LOC spans. The rules would stay as features and as a fallback. Quantity versus fill weight is a context problem, which a tagger learns better than hand-written windows.
- Category would become a simple text classifier (TF-IDF + logistic regression is probably enough).
- I'd add real place spellings from the data to the gazetteer.
- I'd keep about 200 examples held out and report per-field accuracy on those, not on the training data.

## Knowing it works in production
- Log every parse. Compare it with what the buyer or sales team later confirms or edits on the RFQ; every correction is a free label, and the per-field correction rate is the main metric.
- Alert on rising rates of `None` for category or quantity, or of "unknown" locations.
- Run sanity checks, such as quantity < 10 for pcs or gsm > 500.
- Each week, hand-check a random sample of about 50 parses, plus every message with low agreement, and add the failures to the test set.
- Downstream signal: what share of parsed RFQs get supplier quotes without manual re-entry.

## Tools used
Built with Claude Code (Anthropic's Claude, an AI coding assistant).I reviewed and traced the code, added my own test messages, ran the scoring script, tested additional messages, and manually checked the expected outputs.*
