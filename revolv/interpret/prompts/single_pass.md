# version: p1.0.0
SINGLE PASS. Work through four steps in order, then return one JSON object.

Step 1, observe. List the topics, the plain facts (decisions, action items, open questions, key numbers) and the observations a careful listener would note: hedges, soft or firm commitments, answers that do not answer, topic changes, what each person raised or returned to, long gaps before replies against that speaker's median, in-turn pauses, clusters of fillers and restarts, floor-taking, strong or stacked notes. Describe; do not explain.
Step 2, competing readings. Skip the reader if identified. Where observations of two or more kinds cluster for one speaker on one topic, write two or three competing readings, one of them ordinary (thinking time, word-finding, lag, multitasking, second language, mislabelled speaker). Layers: stance_commitment, unsaid, relational.
Step 3, sceptical review. Assume each reading is unproven. Drop any that rests on the voice alone, on a gap alone, on a doubtful speaker label, or that the ordinary explanation fully covers. Drop any that would not change what the reader does next. Reword what survives as one tentative sentence about the moment. Keep at most three per speaker and eight in total. None is a valid result.
Step 4, write up. Notes in the reader's voice; what each other speaker seemed to care about and why; one insight per surviving reading with exact quotes, kinds, moment ids, ordinary alternatives and one follow-up question; up to three next steps.

Put your step 1 to 3 work in the 'working' key first, briefly. It is not shown to the reader, and writing it first will make the rest better.

Shape:
{"working":{"observations":[{"turn_id":"","channel":"","description":""}],
            "rejected":[{"claim":"","reason":""}]},
 "topics":[{"id":"tp1","label":"","spans":[["T001","T014"]],"raised_by":""}],
 "notes":{"summary":"","decisions":[{"text":"","turn_ids":[]}],
          "action_items":[{"owner":"","task":"","due":"","turn_ids":[]}],
          "open_questions":[{"text":"","turn_ids":[]}],
          "key_numbers":[{"text":"","turn_ids":[]}]},
 "speakers":[{"label":"","nothing_notable":false,
              "cares_about":[{"topic_id":"","why":"","turn_ids":[]}]}],
 "insights":[{"id":"ins_001","layer":"","speaker":"","topic_id":"","claim":"",
              "likelihood":"","evidence_confidence":"",
              "evidence":[{"turn_id":"","quote":"","channel":"","moment_ids":[],"description":""}],
              "alternatives":[""],"follow_up":""}],
 "so_what":[{"text":"","refs":[]}]}

<analysis_view>
{{NUMBERED_VIEW}}
</analysis_view>
