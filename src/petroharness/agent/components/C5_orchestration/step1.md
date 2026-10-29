Step 1: reply with what the question asks (point 1), the further points, the intent, your first draft (one or two hypotheses per point, grade "hypothesis") and the actions for your first focus. If the question can be read in more than one way, say in point 1 which reading you answer, or answer each where they need different evidence.{guide_sentence} For example (illustrative content):
{"asks": "Which zones hold hydrocarbon-bearing pay, and how thick is it?",
 "points": ["Where is SW low in reservoir-quality rock?", "Is the low SW supported by resistivity?"],
 "intent": "locate",
 "focus": "Where is SW low in reservoir-quality rock?",
 "edits": [{"op": "add", "point": 1, "text": "Pay likely in the Z2 limestone, a few tens of ft", "grade": "hypothesis"},
           {"op": "add", "point": 2, "text": "LOW_SW likely in the Z2 limestone", "grade": "hypothesis"},
           {"op": "add", "point": 3, "text": "RDEP probably higher in Z2 than below", "grade": "hypothesis"}],
 "next": [{guide_call}{"section": {"key": "hydrocarbon.petrophysical_hydrocarbon_indicators"}}, {"stats": {"curves": ["SW", "RDEP"]}}],
 "done": false}